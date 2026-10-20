import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
import jwt
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from argon2 import PasswordHasher, exceptions as argon2_exceptions
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .database import Base, engine, get_db
from .models import Tenant, User, Membership, Branch, Product, Stock, StockMovement, Sale, SaleLine, Payment, FiscalInvoice, StaffBranch

app=FastAPI(title='DukaSmart POS API',version='0.1.0')
app.add_middleware(CORSMiddleware,allow_origins=os.getenv('CORS_ORIGINS','http://localhost:5173,http://localhost:8000').split(','),allow_credentials=True,allow_methods=['*'],allow_headers=['*'])
SECRET=os.getenv('JWT_SECRET','')
if len(SECRET)<32 and os.getenv('APP_ENV','development')!='development':
    raise RuntimeError('Set JWT_SECRET to at least 32 characters')
SECRET=SECRET or 'development-only-not-for-production-12345'
hasher=PasswordHasher()
# In production use Alembic migrations, not application startup create_all.
if os.getenv('AUTO_CREATE_TABLES','0')=='1': Base.metadata.create_all(engine)
class Signup(BaseModel):
    business_name:str=Field(min_length=2,max_length=180)
    slug:str=Field(pattern=r'^[a-z0-9-]{3,50}$')
    email:EmailStr
    password:str=Field(min_length=12,max_length=128)
class Login(BaseModel):
    email:EmailStr
    password:str
class BranchIn(BaseModel):
    name:str=Field(min_length=1,max_length=100)
    code:str=Field(min_length=1,max_length=30)
class StaffCreate(BaseModel):
    email:EmailStr
    password:str=Field(min_length=12,max_length=128)
    role:Literal['MANAGER','CASHIER','ACCOUNTANT']
    branch_ids:list[str]=Field(min_length=1)
class StaffAssign(BaseModel):
    role:Literal['MANAGER','CASHIER','ACCOUNTANT']
    branch_ids:list[str]=Field(min_length=1)
class TransferIn(BaseModel):
    source_branch_id:str
    destination_branch_id:str
    product_id:str
    quantity:int=Field(gt=0)
    reason:str=Field(min_length=5,max_length=160)
class ProductIn(BaseModel):
    sku:str=Field(min_length=1,max_length=50)
    name:str=Field(min_length=1,max_length=180)
    price:Decimal=Field(ge=0,decimal_places=2)
    cost:Decimal=Field(default=Decimal('0'),ge=0,decimal_places=2)
class ProductEdit(BaseModel):
    sku:str=Field(min_length=1,max_length=50)
    name:str=Field(min_length=1,max_length=180)
    price:Decimal=Field(ge=0,decimal_places=2)
    cost:Decimal=Field(ge=0,decimal_places=2)
class StockAdjust(BaseModel):
    branch_id:str
    product_id:str
    new_quantity:int=Field(ge=0)
    reason:str=Field(min_length=5,max_length=160)
class StockIn(BaseModel):
    branch_id:str
    product_id:str
    quantity:int=Field(gt=0)
class SaleItemIn(BaseModel):
    product_id:str
    quantity:int=Field(gt=0)
class SaleIn(BaseModel):
    branch_id:str
    items:list[SaleItemIn]=Field(min_length=1)
    payment_method:Literal['CASH','MPESA_SANDBOX']
    idempotency_key:str=Field(min_length=8,max_length=100)

def serial(model):
    return {c.name:getattr(model,c.name) for c in model.__table__.columns}
def unique_or_409(db):
    try: db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'Duplicate value or invalid reference')

def auth(authorization:str|None=Header(default=None),db:Session=Depends(get_db)):
    try:
        if not authorization or not authorization.startswith('Bearer '):raise ValueError()
        data=jwt.decode(authorization[7:],SECRET,algorithms=['HS256'])
        user=db.get(User,data['sub'])
        membership=db.scalar(select(Membership).where(Membership.user_id==data['sub'],Membership.tenant_id==data['tenant']))
        if not user or not user.active or not membership:raise ValueError()
        return user,membership
    except Exception:raise HTTPException(401,'Invalid or expired authentication')
def require_branch_access(db,m,branch_id):
    if m.role=='OWNER': return
    assigned=db.scalar(select(StaffBranch).where(StaffBranch.membership_id==m.id,StaffBranch.branch_id==branch_id))
    if not assigned:raise HTTPException(403,'You do not have access to this branch')
def branch_for(db,tenant,branch_id):
    x=db.scalar(select(Branch).where(Branch.tenant_id==tenant,Branch.id==branch_id))
    if not x:raise HTTPException(404,'Branch not found')
    return x
@app.get('/api/v1/health')
def health():return {'status':'ok','environment':os.getenv('APP_ENV','development'),'payment_mode':'sandbox-only','fiscal_mode':'mock-only'}
@app.post('/api/v1/auth/register',status_code=201)
def register(data:Signup,db:Session=Depends(get_db)):
    if db.scalar(select(User).where(User.email==data.email.lower())) or db.scalar(select(Tenant).where(Tenant.slug==data.slug)):
        raise HTTPException(409,'Account or business already exists')
    user=User(email=data.email.lower(),password_hash=hasher.hash(data.password))
    tenant=Tenant(name=data.business_name,slug=data.slug)
    db.add_all([user,tenant]);db.flush()
    db.add(Membership(user_id=user.id,tenant_id=tenant.id,role='OWNER'))
    db.add(Branch(tenant_id=tenant.id,name='Main Branch',code='MAIN'))
    unique_or_409(db)
    return {'tenant_id':tenant.id,'user_id':user.id,'message':'Account created'}
@app.post('/api/v1/auth/login')
def login(data:Login,db:Session=Depends(get_db)):
    user=db.scalar(select(User).where(User.email==data.email.lower()))
    
    try:
        verified = bool(user) and hasher.verify(user.password_hash,data.password)
    except (argon2_exceptions.VerifyMismatchError, argon2_exceptions.VerificationError, argon2_exceptions.InvalidHashError):
        verified = False
    if not verified:raise HTTPException(401,'Invalid credentials')
    memberships=list(db.scalars(select(Membership).where(Membership.user_id==user.id)))
    if not memberships:raise HTTPException(403,'No tenant membership')
    m=memberships[0] # Milestone 1: one business membership per login.
    token=jwt.encode({'sub':user.id,'tenant':m.tenant_id,'exp':datetime.now(timezone.utc)+timedelta(hours=8)},SECRET,algorithm='HS256')
    return {'access_token':token,'token_type':'bearer','tenant_id':m.tenant_id,'role':m.role}
@app.get('/api/v1/tenants/current')
def current(user_membership=Depends(auth),db:Session=Depends(get_db)):
    u,m=user_membership;return serial(db.get(Tenant,m.tenant_id))
@app.get('/api/v1/branches')
def branches(user_membership=Depends(auth),db:Session=Depends(get_db)):
    _,m=user_membership
    q=select(Branch).where(Branch.tenant_id==m.tenant_id)
    if m.role!='OWNER':q=q.join(StaffBranch,StaffBranch.branch_id==Branch.id).where(StaffBranch.membership_id==m.id)
    return [serial(x) for x in db.scalars(q)]
@app.post('/api/v1/branches',status_code=201)
def create_branch(data:BranchIn,user_membership=Depends(auth),db:Session=Depends(get_db)):
    _,m=user_membership
    if m.role!='OWNER':raise HTTPException(403,'Owner permission required')
    b=Branch(tenant_id=m.tenant_id,**data.model_dump());db.add(b);unique_or_409(db);db.refresh(b);return serial(b)
@app.get('/api/v1/staff')
def list_staff(user_membership=Depends(auth),db:Session=Depends(get_db)):
    _,m=user_membership
    if m.role!='OWNER':raise HTTPException(403,'Owner permission required')
    entries=db.execute(select(Membership,User).join(User,User.id==Membership.user_id).where(Membership.tenant_id==m.tenant_id)).all()
    return [{'id':mem.id,'email':usr.email,'role':mem.role,'active':usr.active,'branch_ids':list(db.scalars(select(StaffBranch.branch_id).where(StaffBranch.membership_id==mem.id)))} for mem,usr in entries]
@app.post('/api/v1/staff',status_code=201)
def create_staff(data:StaffCreate,user_membership=Depends(auth),db:Session=Depends(get_db)):
    _,m=user_membership
    if m.role!='OWNER':raise HTTPException(403,'Owner permission required')
    ids=set(data.branch_ids)
    valid=set(db.scalars(select(Branch.id).where(Branch.tenant_id==m.tenant_id,Branch.id.in_(ids))))
    if len(ids)!=len(data.branch_ids) or ids!=valid:raise HTTPException(422,'Select valid unique branches')
    if db.scalar(select(User).where(User.email==data.email.lower())):raise HTTPException(409,'Email already registered; account linking is not supported in this release')
    u=User(email=data.email.lower(),password_hash=hasher.hash(data.password))
    db.add(u);db.flush()
    membership=Membership(user_id=u.id,tenant_id=m.tenant_id,role=data.role)
    db.add(membership);db.flush()
    for bid in ids:db.add(StaffBranch(membership_id=membership.id,branch_id=bid))
    unique_or_409(db)
    return {'id':membership.id,'email':u.email,'role':membership.role,'branch_ids':sorted(ids)}
@app.patch('/api/v1/staff/{membership_id}')
def update_staff(membership_id:str,data:StaffAssign,user_membership=Depends(auth),db:Session=Depends(get_db)):
    _,m=user_membership
    if m.role!='OWNER':raise HTTPException(403,'Owner permission required')
    target=db.scalar(select(Membership).where(Membership.id==membership_id,Membership.tenant_id==m.tenant_id))
    if not target or target.role=='OWNER':raise HTTPException(404,'Editable staff membership not found')
    ids=set(data.branch_ids)
    valid=set(db.scalars(select(Branch.id).where(Branch.tenant_id==m.tenant_id,Branch.id.in_(ids))))
    if len(ids)!=len(data.branch_ids) or ids!=valid:raise HTTPException(422,'Select valid unique branches')
    for row in db.scalars(select(StaffBranch).where(StaffBranch.membership_id==target.id)):db.delete(row)
    db.flush()
    for bid in ids:db.add(StaffBranch(membership_id=target.id,branch_id=bid))
    target.role=data.role;unique_or_409(db)
    return {'id':target.id,'role':target.role,'branch_ids':sorted(ids)}
@app.get('/api/v1/branches/summary')
def branch_summary(user_membership=Depends(auth),db:Session=Depends(get_db)):
    _,m=user_membership
    if m.role!='OWNER':raise HTTPException(403,'Owner permission required')
    out=[]
    for b in db.scalars(select(Branch).where(Branch.tenant_id==m.tenant_id)):
        sales=list(db.scalars(select(Sale).where(Sale.tenant_id==m.tenant_id,Sale.branch_id==b.id)))
        stocks=list(db.scalars(select(Stock).where(Stock.tenant_id==m.tenant_id,Stock.branch_id==b.id)))
        out.append({'id':b.id,'name':b.name,'code':b.code,'sales_count':len(sales),'sales_total':str(sum((x.total for x in sales),Decimal('0'))),'stock_units':sum(x.qty for x in stocks)})
    return out
@app.post('/api/v1/inventory/transfer',status_code=201)
def transfer_stock(data:TransferIn,user_membership=Depends(auth),db:Session=Depends(get_db)):
    _,m=user_membership
    if m.role not in ('OWNER','MANAGER'):raise HTTPException(403)
    if data.source_branch_id==data.destination_branch_id:raise HTTPException(422,'Choose two different branches')
    for bid in [data.source_branch_id,data.destination_branch_id]:
        branch_for(db,m.tenant_id,bid);require_branch_access(db,m,bid)
    if not db.scalar(select(Product).where(Product.id==data.product_id,Product.tenant_id==m.tenant_id)):raise HTTPException(404,'Product not found')
    rows=list(db.scalars(select(Stock).where(Stock.tenant_id==m.tenant_id,Stock.product_id==data.product_id,Stock.branch_id.in_([data.source_branch_id,data.destination_branch_id])).order_by(Stock.branch_id).with_for_update()))
    by_branch={x.branch_id:x for x in rows}
    source=by_branch.get(data.source_branch_id)
    if not source or source.qty<data.quantity:raise HTTPException(409,'Insufficient source stock')
    dest=by_branch.get(data.destination_branch_id)
    if not dest:
        dest=Stock(tenant_id=m.tenant_id,branch_id=data.destination_branch_id,product_id=data.product_id,qty=0);db.add(dest)
    source.qty-=data.quantity;dest.qty+=data.quantity
    ref='TRANSFER-'+secrets.token_hex(8)
    for bid,delta in [(data.source_branch_id,-data.quantity),(data.destination_branch_id,data.quantity)]:
        db.add(StockMovement(tenant_id=m.tenant_id,branch_id=bid,product_id=data.product_id,delta=delta,reason='TRANSFER: '+data.reason,reference=ref))
    unique_or_409(db)
    return {'reference':ref,'source_quantity':source.qty,'destination_quantity':dest.qty}
@app.get('/api/v1/products')
def products(user_membership=Depends(auth),db:Session=Depends(get_db)):
    _,m=user_membership;return [serial(x) for x in db.scalars(select(Product).where(Product.tenant_id==m.tenant_id).order_by(Product.name))]
@app.post('/api/v1/products',status_code=201)
def create_product(data:ProductIn,user_membership=Depends(auth),db:Session=Depends(get_db)):
    _,m=user_membership
    if m.role not in ('OWNER','MANAGER'):raise HTTPException(403)
    p=Product(tenant_id=m.tenant_id,**data.model_dump());db.add(p);unique_or_409(db);db.refresh(p);return serial(p)
@app.patch('/api/v1/products/{product_id}')
def edit_product(product_id:str,data:ProductEdit,user_membership=Depends(auth),db:Session=Depends(get_db)):
    _,m=user_membership
    if m.role not in ('OWNER','MANAGER'):raise HTTPException(403,'Manager permission required')
    p=db.scalar(select(Product).where(Product.id==product_id,Product.tenant_id==m.tenant_id))
    if not p:raise HTTPException(404,'Product not found')
    for k,v in data.model_dump().items():setattr(p,k,v)
    unique_or_409(db);db.refresh(p);return serial(p)

@app.get('/api/v1/inventory/movements')
def inventory_movements(branch_id:str,user_membership=Depends(auth),db:Session=Depends(get_db)):
    _,m=user_membership;branch_for(db,m.tenant_id,branch_id);require_branch_access(db,m,branch_id)
    return [serial(x) for x in db.scalars(select(StockMovement).where(StockMovement.tenant_id==m.tenant_id,StockMovement.branch_id==branch_id).order_by(StockMovement.created_at.desc()).limit(300))]

@app.post('/api/v1/inventory/adjust',status_code=201)
def adjust_stock(data:StockAdjust,user_membership=Depends(auth),db:Session=Depends(get_db)):
    _,m=user_membership
    if m.role not in ('OWNER','MANAGER'):raise HTTPException(403,'Manager permission required')
    branch_for(db,m.tenant_id,data.branch_id);require_branch_access(db,m,data.branch_id)
    p=db.scalar(select(Product).where(Product.id==data.product_id,Product.tenant_id==m.tenant_id))
    if not p:raise HTTPException(404,'Product not found')
    stock=db.scalar(select(Stock).where(Stock.tenant_id==m.tenant_id,Stock.branch_id==data.branch_id,Stock.product_id==data.product_id).with_for_update())
    if stock is None:
        stock=Stock(tenant_id=m.tenant_id,branch_id=data.branch_id,product_id=data.product_id,qty=0)
        db.add(stock)
    delta=data.new_quantity-stock.qty
    if delta==0:return {'quantity':stock.qty,'delta':0}
    stock.qty=data.new_quantity
    db.add(StockMovement(tenant_id=m.tenant_id,branch_id=data.branch_id,product_id=data.product_id,delta=delta,reason='ADJUST: '+data.reason[:32],reference=secrets.token_hex(8)))
    unique_or_409(db)
    return {'quantity':stock.qty,'delta':delta}

@app.get('/api/v1/inventory')
def inventory(branch_id:str,user_membership=Depends(auth),db:Session=Depends(get_db)):
    _,m=user_membership;branch_for(db,m.tenant_id,branch_id);require_branch_access(db,m,branch_id)
    return [serial(x) for x in db.scalars(select(Stock).where(Stock.tenant_id==m.tenant_id,Stock.branch_id==branch_id))]
@app.post('/api/v1/inventory/receive',status_code=201)
def receive(data:StockIn,user_membership=Depends(auth),db:Session=Depends(get_db)):
    _,m=user_membership
    if m.role not in ('OWNER','MANAGER'):raise HTTPException(403)
    branch_for(db,m.tenant_id,data.branch_id);require_branch_access(db,m,data.branch_id)
    p=db.scalar(select(Product).where(Product.id==data.product_id,Product.tenant_id==m.tenant_id))
    if not p:raise HTTPException(404,'Product not found')
    stock=db.scalar(select(Stock).where(Stock.branch_id==data.branch_id,Stock.product_id==data.product_id).with_for_update())
    if not stock:stock=Stock(tenant_id=m.tenant_id,branch_id=data.branch_id,product_id=data.product_id,qty=0);db.add(stock)
    stock.qty+=data.quantity
    db.add(StockMovement(tenant_id=m.tenant_id,branch_id=data.branch_id,product_id=data.product_id,delta=data.quantity,reason='RECEIVE',reference=secrets.token_hex(8)))
    unique_or_409(db);return {'quantity':stock.qty}
@app.post('/api/v1/sales',status_code=201)
def checkout(data:SaleIn,user_membership=Depends(auth),db:Session=Depends(get_db)):
    user,m=user_membership
    if m.role not in ('OWNER','MANAGER','CASHIER'):raise HTTPException(403,'Checkout access required')
    existing=db.scalar(select(Sale).where(Sale.tenant_id==m.tenant_id,Sale.idempotency_key==data.idempotency_key))
    if existing:return {'sale_id':existing.id,'total':str(existing.total),'state':existing.state,'replayed':True}
    branch_for(db,m.tenant_id,data.branch_id);require_branch_access(db,m,data.branch_id)
    if len({i.product_id for i in data.items})!=len(data.items):raise HTTPException(422,'Duplicate product lines')
    product_ids=[i.product_id for i in data.items]
    products={p.id:p for p in db.scalars(select(Product).where(Product.tenant_id==m.tenant_id,Product.id.in_(product_ids)))}
    stocks={s.product_id:s for s in db.scalars(select(Stock).where(Stock.tenant_id==m.tenant_id,Stock.branch_id==data.branch_id,Stock.product_id.in_(product_ids)).with_for_update())}
    if len(products)!=len(product_ids):raise HTTPException(404,'Product not found')
    for i in data.items:
        if i.product_id not in stocks or stocks[i.product_id].qty<i.quantity:raise HTTPException(409,'Insufficient stock for '+products[i.product_id].name)
    total=sum((products[i.product_id].price*i.quantity for i in data.items),Decimal('0'))
    sale=Sale(tenant_id=m.tenant_id,branch_id=data.branch_id,cashier_id=user.id,idempotency_key=data.idempotency_key,total=total,state='SIMULATED_PAID' if data.payment_method=='MPESA_SANDBOX' else 'CASH_RECORDED')
    db.add(sale);db.flush()
    for i in data.items:
        p=products[i.product_id]
        db.add(SaleLine(sale_id=sale.id,product_id=p.id,qty=i.quantity,unit_price=p.price,cost_snapshot=p.cost,tax_code_snapshot=p.tax_code))
        stocks[p.id].qty-=i.quantity
        db.add(StockMovement(tenant_id=m.tenant_id,branch_id=data.branch_id,product_id=p.id,delta=-i.quantity,reason='SALE',reference=sale.id))
    db.add(Payment(tenant_id=m.tenant_id,sale_id=sale.id,method=data.payment_method,amount=total,status='SIMULATED' if data.payment_method=='MPESA_SANDBOX' else 'CASH_RECORDED'))
    db.add(FiscalInvoice(tenant_id=m.tenant_id,sale_id=sale.id,state='NOT_SUBMITTED',provider='MOCK'))
    unique_or_409(db)
    return {'sale_id':sale.id,'total':str(total),'state':sale.state,'fiscal_state':'NOT_SUBMITTED','replayed':False}
@app.get('/api/v1/sales')
def sales(user_membership=Depends(auth),db:Session=Depends(get_db)):
    _,m=user_membership
    q=select(Sale).where(Sale.tenant_id==m.tenant_id)
    if m.role!='OWNER':q=q.where(Sale.branch_id.in_(select(StaffBranch.branch_id).where(StaffBranch.membership_id==m.id)))
    return [serial(x) for x in db.scalars(q.order_by(Sale.created_at.desc()).limit(100))]
@app.get('/api/v1/fiscal/invoices')
def fiscal_invoices(user_membership=Depends(auth),db:Session=Depends(get_db)):
    _,m=user_membership
    q=select(FiscalInvoice).join(Sale,Sale.id==FiscalInvoice.sale_id).where(FiscalInvoice.tenant_id==m.tenant_id)
    if m.role!='OWNER':q=q.where(Sale.branch_id.in_(select(StaffBranch.branch_id).where(StaffBranch.membership_id==m.id)))
    return [serial(x) for x in db.scalars(q)]
@app.post('/api/v1/fiscal/invoices/{sale_id}/simulate')
def fiscal_simulate(sale_id:str,user_membership=Depends(auth),db:Session=Depends(get_db)):
    _,m=user_membership
    if m.role not in ('OWNER','MANAGER','ACCOUNTANT'):raise HTTPException(403)
    sale=db.scalar(select(Sale).where(Sale.id==sale_id,Sale.tenant_id==m.tenant_id))
    if not sale:raise HTTPException(404)
    require_branch_access(db,m,sale.branch_id)
    inv=db.scalar(select(FiscalInvoice).where(FiscalInvoice.tenant_id==m.tenant_id,FiscalInvoice.sale_id==sale_id))
    if not inv:raise HTTPException(404)
    # Deliberately never generates a KRA invoice number or a compliant fiscal status.
    inv.state='MOCK_ACKNOWLEDGED'
    inv.provider_response='Simulated partner acknowledgement. Not an eTIMS receipt.'
    unique_or_409(db)
    return {'state':inv.state,'warning':'Simulation only — NOT a KRA tax invoice'}

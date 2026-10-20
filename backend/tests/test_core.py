import os
os.environ['APP_ENV']='development'
os.environ['JWT_SECRET']='unit-test-key-longer-than-thirty-two-characters'
from fastapi.testclient import TestClient
from app.database import Base,engine
from app.main import app

def test_health():
    r=TestClient(app).get('/api/v1/health')
    assert r.status_code==200
    assert r.json()['payment_mode']=='sandbox-only'

def test_tenant_isolation_and_sale(tmp_path):
    Base.metadata.create_all(engine)
    c=TestClient(app)
    import uuid
    tag=uuid.uuid4().hex[:10]
    def setup(n):
        email=f'{n}{tag}@example.com'
        r=c.post('/api/v1/auth/register',json={'business_name':n,'slug':n.lower()+tag,'email':email,'password':'StrongTestPassword123!'})
        assert r.status_code==201,r.text
        token=c.post('/api/v1/auth/login',json={'email':email,'password':'StrongTestPassword123!'}).json()['access_token']
        return {'Authorization':'Bearer '+token}
    a=setup('ShopA');b=setup('ShopB')
    branch=c.get('/api/v1/branches',headers=a).json()[0]['id']
    p=c.post('/api/v1/products',headers=a,json={'sku':'001','name':'Sugar','price':'200.00','cost':'130.00'}).json()
    assert c.get('/api/v1/products',headers=b).json()==[]
    assert c.post('/api/v1/inventory/receive',headers=b,json={'branch_id':branch,'product_id':p['id'],'quantity':5}).status_code==404
    assert c.post('/api/v1/inventory/receive',headers=a,json={'branch_id':branch,'product_id':p['id'],'quantity':5}).status_code==201
    payload={'branch_id':branch,'items':[{'product_id':p['id'],'quantity':2}],'payment_method':'MPESA_SANDBOX','idempotency_key':'checkout-001-'+tag}
    result=c.post('/api/v1/sales',headers=a,json=payload)
    assert result.status_code==201,result.text
    assert result.json()['total']=='400.00'
    assert c.post('/api/v1/sales',headers=a,json=payload).json()['replayed'] is True
    assert c.get('/api/v1/inventory?branch_id='+branch,headers=a).json()[0]['qty']==3
    assert c.get('/api/v1/sales',headers=b).json()==[]
    assert c.post('/api/v1/sales',headers=a,json={**payload,'idempotency_key':'checkout-002-'+tag,'items':[{'product_id':p['id'],'quantity':8}]}).status_code==409

def test_branches_staff_and_transfers():
    import uuid
    c=TestClient(app)
    tag=uuid.uuid4().hex[:9]
    email=f'owner{tag}@example.com'
    assert c.post('/api/v1/auth/register',json={'business_name':'Branches Test','slug':'branches-'+tag,'email':email,'password':'StrongTestPassword123!'}).status_code==201
    token=c.post('/api/v1/auth/login',json={'email':email,'password':'StrongTestPassword123!'}).json()['access_token']
    h={'Authorization':'Bearer '+token}
    a=c.get('/api/v1/branches',headers=h).json()[0]['id']
    r=c.post('/api/v1/branches',headers=h,json={'name':'Outlet Two','code':'TWO'})
    assert r.status_code==201,r.text
    b=r.json()['id']
    product=c.post('/api/v1/products',headers=h,json={'name':'Rice','sku':'RICE'+tag,'price':'200','cost':'100'}).json()['id']
    assert c.post('/api/v1/inventory/receive',headers=h,json={'branch_id':a,'product_id':product,'quantity':30}).status_code==201
    t=c.post('/api/v1/inventory/transfer',headers=h,json={'source_branch_id':a,'destination_branch_id':b,'product_id':product,'quantity':12,'reason':'Replenish outlet'})
    assert t.status_code==201,t.text
    assert c.get('/api/v1/inventory?branch_id='+a,headers=h).json()[0]['qty']==18
    assert c.get('/api/v1/inventory?branch_id='+b,headers=h).json()[0]['qty']==12
    staff_email=f'cashier{tag}@example.com'
    result=c.post('/api/v1/staff',headers=h,json={'email':staff_email,'password':'StrongTestPassword123!','role':'CASHIER','branch_ids':[b]})
    assert result.status_code==201,result.text
    staff_token=c.post('/api/v1/auth/login',json={'email':staff_email,'password':'StrongTestPassword123!'}).json()['access_token']
    sh={'Authorization':'Bearer '+staff_token}
    assert len(c.get('/api/v1/branches',headers=sh).json())==1
    assert c.get('/api/v1/inventory?branch_id='+a,headers=sh).status_code==403
    assert c.get('/api/v1/inventory?branch_id='+b,headers=sh).status_code==200
    assert c.post('/api/v1/branches',headers=sh,json={'name':'Wrong','code':'NO'}).status_code==403
    assert c.get('/api/v1/staff',headers=sh).status_code==403
    assert c.post('/api/v1/inventory/transfer',headers=h,json={'source_branch_id':a,'destination_branch_id':b,'product_id':product,'quantity':100,'reason':'Too many units'}).status_code==409

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import String, ForeignKey, Numeric, DateTime, UniqueConstraint, CheckConstraint, Text, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

def uid(): return str(uuid.uuid4())
def now(): return datetime.now(timezone.utc)
class Tenant(Base):
    __tablename__='tenants'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    name: Mapped[str]=mapped_column(String(180))
    slug: Mapped[str]=mapped_column(String(80),unique=True)
    kra_pin: Mapped[str|None]=mapped_column(String(30),nullable=True)
    status: Mapped[str]=mapped_column(String(24),default='ACTIVE')
class User(Base):
    __tablename__='users'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    email: Mapped[str]=mapped_column(String(255),unique=True)
    password_hash: Mapped[str]=mapped_column(String(255))
    active: Mapped[bool]=mapped_column(Boolean,default=True)
class Membership(Base):
    __tablename__='memberships'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    user_id: Mapped[str]=mapped_column(ForeignKey('users.id'))
    tenant_id: Mapped[str]=mapped_column(ForeignKey('tenants.id'))
    role: Mapped[str]=mapped_column(String(20),default='OWNER')
    __table_args__=(UniqueConstraint('user_id','tenant_id'),)
class Branch(Base):
    __tablename__='branches'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    tenant_id: Mapped[str]=mapped_column(ForeignKey('tenants.id'),index=True)
    name: Mapped[str]=mapped_column(String(100))
    code: Mapped[str]=mapped_column(String(30))
    __table_args__=(UniqueConstraint('tenant_id','code'),)
class Product(Base):
    __tablename__='products'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    tenant_id: Mapped[str]=mapped_column(ForeignKey('tenants.id'),index=True)
    sku: Mapped[str]=mapped_column(String(50))
    name: Mapped[str]=mapped_column(String(180))
    price: Mapped[Decimal]=mapped_column(Numeric(14,2))
    cost: Mapped[Decimal]=mapped_column(Numeric(14,2),default=0)
    tax_code: Mapped[str]=mapped_column(String(30),default='UNMAPPED')
    __table_args__=(UniqueConstraint('tenant_id','sku'),CheckConstraint('price >= 0'),CheckConstraint('cost >= 0'))
class Stock(Base):
    __tablename__='stock_balances'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    tenant_id: Mapped[str]=mapped_column(ForeignKey('tenants.id'))
    branch_id: Mapped[str]=mapped_column(ForeignKey('branches.id'))
    product_id: Mapped[str]=mapped_column(ForeignKey('products.id'))
    qty: Mapped[int]=mapped_column(Integer,default=0)
    __table_args__=(UniqueConstraint('branch_id','product_id'),CheckConstraint('qty >= 0'))
class StockMovement(Base):
    __tablename__='stock_movements'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    tenant_id: Mapped[str]=mapped_column(ForeignKey('tenants.id'))
    branch_id: Mapped[str]=mapped_column(ForeignKey('branches.id'))
    product_id: Mapped[str]=mapped_column(ForeignKey('products.id'))
    delta: Mapped[int]=mapped_column(Integer)
    reason: Mapped[str]=mapped_column(String(40))
    reference: Mapped[str]=mapped_column(String(80))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class Sale(Base):
    __tablename__='sales'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    tenant_id: Mapped[str]=mapped_column(ForeignKey('tenants.id'),index=True)
    branch_id: Mapped[str]=mapped_column(ForeignKey('branches.id'))
    cashier_id: Mapped[str]=mapped_column(ForeignKey('users.id'))
    idempotency_key: Mapped[str]=mapped_column(String(100))
    total: Mapped[Decimal]=mapped_column(Numeric(14,2))
    state: Mapped[str]=mapped_column(String(24),default='COMPLETED')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    __table_args__=(UniqueConstraint('tenant_id','idempotency_key'),)
class SaleLine(Base):
    __tablename__='sale_lines'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    sale_id: Mapped[str]=mapped_column(ForeignKey('sales.id'))
    product_id: Mapped[str]=mapped_column(ForeignKey('products.id'))
    qty: Mapped[int]=mapped_column(Integer)
    unit_price: Mapped[Decimal]=mapped_column(Numeric(14,2))
    cost_snapshot: Mapped[Decimal]=mapped_column(Numeric(14,2))
    tax_code_snapshot: Mapped[str]=mapped_column(String(30))
class Payment(Base):
    __tablename__='payments'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    tenant_id: Mapped[str]=mapped_column(ForeignKey('tenants.id'))
    sale_id: Mapped[str]=mapped_column(ForeignKey('sales.id'))
    method: Mapped[str]=mapped_column(String(20))
    status: Mapped[str]=mapped_column(String(30),default='SIMULATED')
    amount: Mapped[Decimal]=mapped_column(Numeric(14,2))
    provider_reference: Mapped[str|None]=mapped_column(String(100),nullable=True)
class FiscalInvoice(Base):
    __tablename__='fiscal_invoices'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    tenant_id: Mapped[str]=mapped_column(ForeignKey('tenants.id'))
    sale_id: Mapped[str]=mapped_column(ForeignKey('sales.id'),unique=True)
    state: Mapped[str]=mapped_column(String(30),default='NOT_SUBMITTED')
    provider: Mapped[str]=mapped_column(String(50),default='MOCK')
    external_reference: Mapped[str|None]=mapped_column(String(100),nullable=True)
    provider_response: Mapped[str|None]=mapped_column(Text,nullable=True)

class StaffBranch(Base):
    __tablename__='staff_branches'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    membership_id: Mapped[str]=mapped_column(ForeignKey('memberships.id',ondelete='CASCADE'),index=True)
    branch_id: Mapped[str]=mapped_column(ForeignKey('branches.id',ondelete='CASCADE'),index=True)
    __table_args__=(UniqueConstraint('membership_id','branch_id'),)

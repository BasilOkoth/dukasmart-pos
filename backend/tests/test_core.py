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

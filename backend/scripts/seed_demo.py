from src.config.database import Base,engine,Session
from src.models.identity import User,Audit
from src.models.dataset import Dataset
from src.models.plan import Plan
from src.models.trace import Trace
from src.models.review import Review
from src.utils.security import hash_password
DEFAULT_STEPS=[{'op':'scan','source':'readings'},{'op':'filter','field':'value','compare':'gte','value':50},{'op':'hash_join','right':'sensors','left_key':'sensor_id','right_key':'sensor_id'},{'op':'group','keys':['zone'],'measure':'value','aggregate':'avg'}]
def seed():
 Base.metadata.create_all(engine)
 with Session() as s:
  for role in ('admin','operator','viewer'):
   if not s.query(User).filter_by(email=role+'@operator.local').first():s.add(User(email=role+'@operator.local',role=role,password=hash_password('Trace2026!')))
  sensors=[{'sensor_id':i,'zone':['北场','南场','试验间'][i%3],'device_type':['pump','motor','valve'][i%3]} for i in range(1,13)]
  readings=[{'sensor_id':i%12+1,'value':round(25+(i*13%800)/10,1),'recorded_at':f'2026-11-17T{8+i//60:02d}:{i%60:02d}:00'} for i in range(240)]
  seeds=[('松原日班温升采样',sensors,readings,'240条采样 / 12个传感器 / 区域温升复核'),('空数据边界',[],[],'验证空输入和空聚合'),('重复键校验',[{'sensor_id':1,'zone':'北场','device_type':'pump'},{'sensor_id':1,'zone':'复核点','device_type':'pump'}],[{'sensor_id':1,'value':80,'recorded_at':'2026-11-17T09:00:00'}],'右表重复键必须保留连接倍数')]
  for name,a,b,desc in seeds:
   if not s.query(Dataset).filter_by(name=name).first():s.add(Dataset(name=name,sensors=a,readings=b,description=desc))
  s.flush()
  for i,(name,_,_,_) in enumerate(seeds):
   pname=['过滤-连接-分组基线','空输入管线','重复键内连接'][i]
   if not s.query(Plan).filter_by(name=pname).first():s.add(Plan(name=pname,dataset_id=s.query(Dataset).filter_by(name=name).one().id,steps=DEFAULT_STEPS,note='受限DSL，Python算子真实执行'))
  s.flush()
  baseline_name='基线快照 · 松原日班温升采样'
  if not s.query(Trace).filter_by(name=baseline_name).first():
   from src.services.operators import execute
   dataset=s.query(Dataset).filter_by(name=seeds[0][0]).one();plan=s.query(Plan).filter_by(name='过滤-连接-分组基线').one()
   snapshot={'dataset':{'id':dataset.id,'name':dataset.name,'description':dataset.description,'sensors':dataset.sensors,'readings':dataset.readings},
    'plan':{'id':plan.id,'name':plan.name,'dataset_id':plan.dataset_id,'steps':plan.steps,'note':plan.note}}
   s.add(Trace(name=baseline_name,plan_id=plan.id,dataset_id=dataset.id,status='completed',snapshot=snapshot,result=execute(snapshot['dataset'],plan.steps)))
  s.commit();counts={m.__tablename__:s.query(m).count() for m in (User,Dataset,Plan,Trace,Review)};print(counts);return counts
if __name__=='__main__':seed()

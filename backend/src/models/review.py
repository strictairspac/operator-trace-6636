from sqlalchemy import Column,Integer,String,JSON,DateTime,func,ForeignKey
from src.config.database import Base
class Review(Base):
 __tablename__='reviews'
 id=Column(Integer,primary_key=True)
 name=Column(String(120),unique=True,nullable=False)
 dataset_id=Column(Integer,ForeignKey('datasets.id'),nullable=False)
 plan_id=Column(Integer,ForeignKey('plans.id'),nullable=False)
 baseline_trace_id=Column(Integer,ForeignKey('traces.id'),nullable=False)
 candidate_trace_id=Column(Integer,ForeignKey('traces.id'),nullable=True)
 status=Column(String(20),default='queued',nullable=False)
 result=Column(JSON,nullable=True)
 error=Column(String(1000),nullable=True)
 progress=Column(JSON,nullable=True)
 attempts=Column(Integer,nullable=False,default=1)
 created_at=Column(DateTime,server_default=func.now())
 updated_at=Column(DateTime,server_default=func.now(),onupdate=func.now())

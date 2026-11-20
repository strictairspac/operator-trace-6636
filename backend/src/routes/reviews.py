import json
from fastapi import APIRouter,Depends
from fastapi.responses import Response
from src.middlewares.auth import current,writer
from src.schemas.business import ReviewInput
from src.services import reviews
from src.controllers.business import start_review
router=APIRouter()
@router.get('/reviews')
def listing(u=Depends(current)):return reviews.list_items()
@router.post('/reviews')
def create(data:ReviewInput,u=Depends(writer)):return start_review(data,u)
@router.get('/reviews/{item_id}')
def detail(item_id:int,u=Depends(current)):return reviews.detail(item_id)
@router.post('/reviews/{item_id}/retry')
def retry(item_id:int,u=Depends(writer)):return reviews.retry(item_id)
@router.get('/reviews/{item_id}/export')
def export(item_id:int,u=Depends(current)):
 return Response(json.dumps(reviews.detail(item_id),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="review-{item_id}.json"'})

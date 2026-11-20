"""Pure reconciliation rules: operator alignment, semantic diff and regression checks.

Every comparison uses the trace's own accepted snapshot. A step is only proven
identical when the operator, its canonical parameters and its input checksum all
match. Different operators are never paired; ambiguous steps stay unmatched.
"""
import hashlib,json
from collections import Counter

NUMERIC_PRECISION=6
DURATION_REGRESSION_RATIO=1.5
DURATION_REGRESSION_MIN_MS=1.0
ROW_VISIT_REGRESSION_RATIO=1.2
STEP_REGRESSION_RATIO=2.0
KINDS=('identical','changed','unproven','added','removed','conflict')
VERDICT_LABELS={'identical':'逐算子一致','result_equal_steps_unproven':'结果一致 / 步骤不可证','diverged':'存在分歧'}

def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def checksum(rows):return hashlib.sha256(canonical(rows).encode()).hexdigest()

def _number(value):
 rounded=round(float(value),NUMERIC_PRECISION)
 return 0.0 if rounded==0 else rounded

def row_signature(row):return canonical({k:(_number(v) if isinstance(v,(int,float)) and not isinstance(v,bool) else v) for k,v in row.items()})

def _preview(counter):
 out=[]
 for signature,count in sorted(counter.items()):
  out.append({'row':json.loads(signature),'count':count})
  if len(out)>=5:break
 return out

def compare_rows(baseline,new):
 left=Counter(row_signature(r) for r in baseline);right=Counter(row_signature(r) for r in new)
 only_left=left-right;only_right=right-left
 return {'equal':left==right,'baseline_rows':len(baseline),'new_rows':len(new),
  'difference_count':sum(only_left.values())+sum(only_right.values()),
  'only_baseline':_preview(only_left),'only_new':_preview(only_right),
  'baseline_checksum':checksum(baseline),'new_checksum':checksum(new),
  'precision':NUMERIC_PRECISION,'duplicate_policy':'multiset; duplicate rows retain multiplicity'}

def step_descriptors(trace):
 snapshot=trace.get('snapshot') or {};result=trace.get('result') or {}
 steps=(snapshot.get('plan') or {}).get('steps') or []
 operators=result.get('operators') or []
 if len(steps)!=len(operators):raise ValueError('执行快照与逐步摘要不一致，无法逐算子对账')
 incoming=checksum((snapshot.get('dataset') or {}).get('readings') or [])
 descriptors=[]
 for index,(step,operator) in enumerate(zip(steps,operators)):
  descriptors.append({'index':index,'op':step.get('op'),'step':step,'spec':canonical(step),
   'input_checksum':incoming,'output_checksum':operator.get('checksum'),
   'input_rows':operator.get('input_rows',0),'output_rows':operator.get('output_rows',0),
   'duration_ms':operator.get('duration_ms',0.0),'detail':operator.get('detail') or {}})
  incoming=operator.get('checksum')
 return descriptors

def signature(baseline,new):
 payload={'baseline':[(s['spec'],s['input_checksum'],s['output_checksum']) for s in baseline],
  'new':[(s['spec'],s['input_checksum'],s['output_checksum']) for s in new]}
 return checksum(payload)

def provably_identical(left,right):
 return left['op']==right['op'] and left['spec']==right['spec'] and left['input_checksum']==right['input_checksum']

def _anchors(baseline,new):
 rows,cols=len(baseline),len(new)
 table=[[0]*(cols+1) for _ in range(rows+1)]
 for i in range(rows-1,-1,-1):
  for j in range(cols-1,-1,-1):
   table[i][j]=1+table[i+1][j+1] if provably_identical(baseline[i],new[j]) else max(table[i+1][j],table[i][j+1])
 pairs=[];i=j=0
 while i<rows and j<cols:
  if provably_identical(baseline[i],new[j]):pairs.append((i,j));i+=1;j+=1
  elif table[i+1][j]>=table[i][j+1]:i+=1
  else:j+=1
 return pairs

def _slim(step):
 if not step:return None
 return {k:step[k] for k in ('index','op','step','spec','input_rows','output_rows','input_checksum','output_checksum','duration_ms','detail')}

def _entry(kind,baseline=None,new=None,reason=''):
 entry={'kind':kind,'reason':reason,'op':(new or baseline)['op'],
  'baseline_index':baseline['index'] if baseline else None,'new_index':new['index'] if new else None,
  'baseline':_slim(baseline),'new':_slim(new),'duration_delta_ms':None,'slowdown_ratio':None}
 if baseline and new:
  entry['duration_delta_ms']=round(new['duration_ms']-baseline['duration_ms'],4)
  entry['slowdown_ratio']=round(new['duration_ms']/baseline['duration_ms'],4) if baseline['duration_ms']>0 else None
 return entry

def entry_key(entry):return f"{entry['baseline_index']}:{entry['new_index']}:{entry['kind']}"

def _classify(baseline,new):
 if baseline['spec']==new['spec'] and baseline['input_checksum']==new['input_checksum']:
  if baseline['output_checksum']==new['output_checksum']:return 'identical','算子与参数相同且输入摘要一致，输出摘要相同'
  return 'conflict','算子与参数相同且输入摘要一致，但输出摘要不同'
 if baseline['op']=='scan' and baseline['input_checksum']!=new['input_checksum']:
  return 'unproven','数据集快照内容不同，无法证明扫描语义相同'
 if baseline['input_checksum']==new['input_checksum']:return 'changed','同一算子的参数被调整，输入相同但参数不同，无法证明语义相同'
 if baseline['spec']!=new['spec']:return 'unproven','上游输出不同且算子参数不同，无法证明该步骤语义相同'
 return 'unproven','上游输出不同，无法证明该步骤语义相同'

def build_ledger(baseline,new,confirmed=None):
 confirmed=confirmed or {};ledger=[]
 def add(kind,left=None,right=None,reason=''):
  entry=_entry(kind,left,right,reason);entry=confirmed.get(entry_key(entry),entry);ledger.append(entry)
 i=j=0
 for anchor_b,anchor_n in _anchors(baseline,new)+[(len(baseline),len(new))]:
  left_run=baseline[i:anchor_b];right_run=new[j:anchor_n];used=set()
  for left in left_run:
   match=next((right for right in right_run if right['index'] not in used and right['op']==left['op']),None)
   if match:
    used.add(match['index']);kind,reason=_classify(left,match);add(kind,left,match,reason)
   else:add('removed',left,None,'基线步骤在新执行中被删除')
  for right in right_run:
   if right['index'] not in used:add('added',None,right,'新执行新增步骤')
  if anchor_b<len(baseline):
   kind,reason=_classify(baseline[anchor_b],new[anchor_n]);add(kind,baseline[anchor_b],new[anchor_n],reason)
  i=anchor_b+1;j=anchor_n+1
 return ledger

def _change(before,after):
 before=float(before or 0);after=float(after or 0);delta=round(after-before,4)
 return {'baseline':before,'new':after,'delta':delta,'ratio':round(after/before,4) if before>0 else None}

def regression_summary(baseline_result,new_result,ledger):
 total=_change(baseline_result.get('duration_ms'),new_result.get('duration_ms'))
 visits=_change(baseline_result.get('row_visits'),new_result.get('row_visits'))
 outputs=_change(baseline_result.get('output_rows'),new_result.get('output_rows'))
 steps=[];signals=[]
 for entry in ledger:
  if not entry['baseline'] or not entry['new']:continue
  metric=_change(entry['baseline']['duration_ms'],entry['new']['duration_ms'])
  metric.update({'op':entry['op'],'kind':entry['kind'],'baseline_index':entry['baseline_index'],'new_index':entry['new_index']})
  metric['comparable']=entry['kind']=='identical'
  metric['regressed']=metric['comparable'] and metric['ratio'] is not None and metric['ratio']>=STEP_REGRESSION_RATIO and metric['delta']>=DURATION_REGRESSION_MIN_MS
  if metric['regressed']:signals.append(f"step:{entry['new_index']}:{entry['op']}")
  steps.append(metric)
 if total['ratio'] is not None and total['ratio']>=DURATION_REGRESSION_RATIO and total['delta']>=DURATION_REGRESSION_MIN_MS:signals.append('total_duration')
 if visits['ratio'] is not None and visits['ratio']>=ROW_VISIT_REGRESSION_RATIO and visits['delta']>=1:signals.append('row_visits')
 return {'status':'regressed' if signals else 'stable','signals':signals,
  'thresholds':{'duration_ratio':DURATION_REGRESSION_RATIO,'min_ms':DURATION_REGRESSION_MIN_MS,
   'row_visit_ratio':ROW_VISIT_REGRESSION_RATIO,'step_ratio':STEP_REGRESSION_RATIO},
  'total':total,'row_visits':visits,'output_rows':outputs,'steps':steps}

def build_conclusion(baseline,new,baseline_result,new_result,ledger,output):
 counts={kind:0 for kind in KINDS}
 for entry in ledger:counts[entry['kind']]=counts.get(entry['kind'],0)+1
 first=next((entry for entry in ledger if entry['kind']!='identical'),None)
 if not first and not output['equal']:
  first={'kind':'output','reason':'逐步摘要一致但最终输出不同','op':None,'baseline_index':None,'new_index':None,
   'baseline':None,'new':None,'duration_delta_ms':None,'slowdown_ratio':None}
 if not first and not counts['identical']:verdict='diverged'
 elif counts['conflict'] or not output['equal']:verdict='diverged'
 elif counts['identical']==len(ledger):verdict='identical'
 else:verdict='result_equal_steps_unproven'
 return {'verdict':verdict,'verdict_label':VERDICT_LABELS[verdict],
  'baseline':baseline,'new':new,'counts':counts,'ledger':ledger,
  'first_divergence':first,
  'unmatched_steps':[entry for entry in ledger if entry['kind'] in ('added','removed')],
  'unproven_steps':[entry for entry in ledger if entry['kind'] in ('changed','unproven','conflict')],
  'output':output,'regression':regression_summary(baseline_result,new_result,ledger),
  'rules':{'baseline':'同一数据集；按各自受理快照核对','numeric_precision':NUMERIC_PRECISION,
   'duplicates':'重复行按重数比较','empty':'仅当双方均为空结果时相等','matching':'算子、参数与输入摘要全部一致才可证明相同'}}

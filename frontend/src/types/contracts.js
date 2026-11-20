/** @typedef {{id:number,name:string,sensors:object[],readings:object[]}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,steps:object[]}} Plan */
/** @typedef {{id:number,name:string,status:'queued'|'running'|'completed'|'failed',result:object|null}} Trace */
/** @typedef {{id:number,name:string,dataset_id:number,baseline_trace_id:number,candidate_trace_id:number|null,status:'queued'|'running'|'completed'|'failed',result:object|null,progress:object,attempts:number}} Review */
export {};

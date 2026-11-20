import {datasets,plans,traces,reviews} from '../api/business.js';
export const store={datasets:[],plans:[],traces:[],reviews:[],user:null};
export async function refresh(){[store.datasets,store.plans,store.traces,store.reviews]=await Promise.all([datasets.list(),plans.list(),traces.list(),reviews.list()]);}

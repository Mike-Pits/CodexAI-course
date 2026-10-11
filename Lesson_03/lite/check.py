"""Execute the six required Lite scenarios against a real model and save evidence."""
import os
from datetime import datetime, timezone
from lite.core import ROOT, ModelClient, read_json, write_json, recruit, sell

def main():
    out=ROOT/'results'/datetime.now(timezone.utc).strftime('lite-%Y%m%dT%H%M%S%fZ')
    client=ModelClient(out/'calls.jsonl',max_calls=20)
    cases=read_json(ROOT/'data/lite_cases.json')
    model=os.getenv('WORKER_MODEL','')
    vacancy=(ROOT/'data/vacancy.txt').read_text()
    failures=[]
    selected_recruiter = os.getenv('LITE_RECRUITER_CASE')
    selected_sales = os.getenv('LITE_SALES_CASE')
    for case in cases['recruiter']:
        if selected_recruiter and case['id'] != selected_recruiter:
            continue
        try:
            result=recruit(client,model,vacancy,case['resume'],tag='lite/'+case['id'])
            write_json(out/f"recruiter-{case['id']}.json",{'case':case,'result':result})
        except Exception as exc:
            failures.append({'kind':'recruiter','case':case['id'],'error':type(exc).__name__+': '+str(exc)})
            write_json(out/f"recruiter-{case['id']}.json",{'case':case,'error':failures[-1]['error']})
    for case in cases['sales']:
        if selected_sales and case['id'] != selected_sales:
            continue
        history=[]
        dialogue_error=None
        for message in case['messages']:
            history.append({'role':'user','content':message})
            try:
                answer=sell(client,model,history,tag='lite/'+case['id'])
            except Exception as exc:
                dialogue_error=type(exc).__name__+': '+str(exc)
                failures.append({'kind':'sales','case':case['id'],'message':message,'error':dialogue_error})
                break
            history.append({'role':'assistant','content':answer['message']})
        payload={'case':case,'dialogue':history}
        if dialogue_error:
            payload['error']=dialogue_error
        write_json(out/f"sales-{case['id']}.json",payload)
    status='completed' if not failures else 'partial'
    write_json(out/'manifest.json',{'status':status,'actual_requests':client.calls,'model':model,'failures':failures})
    print(out)

if __name__=='__main__':main()

"""A tiny real structured-output request per distinct configured model."""
import os
from datetime import datetime, timezone
from lite.core import ROOT, ModelClient, obj, S, write_json

def main():
    models=list(dict.fromkeys(os.getenv(role+'_MODEL','') for role in ['WORKER','JUDGE','CLIENT']))
    if '' in models:raise SystemExit('Модели не заданы. Сначала выполните bash scripts/setup_openai.sh')
    out=ROOT/'results'/datetime.now(timezone.utc).strftime('preflight-%Y%m%dT%H%M%S%fZ')
    client=ModelClient(out/'calls.jsonl',max_calls=len(models))
    if not client.key:raise SystemExit('Ключ не задан. Сначала выполните bash scripts/setup_openai.sh')
    results=[]
    try:
        for model in models:
            result=client.ask(model,'Ответь кратко по JSON-схеме.', [{'role':'user','content':'Проверка соединения. Верни message: ok.'}],obj({'message':S}),'preflight')
            results.append({'model':model,'result':result})
            print(model+': подключение и структурированный ответ работают',flush=True)
    finally:
        write_json(out/'status.json',{'results':results,'actual_requests':client.calls,'all_models_passed':len(results)==len(models)})

if __name__=='__main__':main()

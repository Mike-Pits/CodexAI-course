"""python3 -m pro.run --iterations 2 --max-calls 1000; no API requests with --plan."""
import argparse
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from lite.core import ROOT, ModelClient, read_json, write_json, prompt, recruit
from pro.evaluate import simulate, optimize, recruiter_metrics, sales_metrics
from lite.core import recruit_checks


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def run(args):
    resumes = read_json(ROOT/'data/resumes.json')
    scenarios = read_json(ROOT/'data/scenarios.json')
    if args.smoke:
        resumes = [next(r for r in resumes if r['split']==s) for s in ['train','validation','holdout']]
        scenarios = [next(r for r in scenarios if r['split']==s) for s in ['train','validation','holdout']]
    # References once; train+validation for every version; two holdout versions;
    # two optimizers between iterations. Each dialogue = 2*turns calls including judge.
    count = len(resumes) + sum(r['split']!='holdout' for r in resumes)*args.iterations + sum(r['split']=='holdout' for r in resumes)*2
    count += (sum(r['split']!='holdout' for r in scenarios)*args.iterations + sum(r['split']=='holdout' for r in scenarios)*2)*2*args.turns
    count += 2*(args.iterations-1)
    plan = {'mode':'smoke' if args.smoke else 'full','iterations':args.iterations,'turns':args.turns,'planned_requests':count,
            'resumes':len(resumes),'scenarios':len(scenarios),'max_calls':args.max_calls,
            'note':'Без повторов запросов; при ошибке прогон останавливается, промежуточные результаты сохраняются.'}
    print(plan,flush=True)
    if args.plan:
        return
    if count > args.max_calls:
        raise ValueError('План превышает --max-calls. Увеличьте лимит или используйте --smoke.')
    models = {role:os.getenv(role.upper()+'_MODEL','') for role in ['worker','judge','client']}
    if not (os.getenv('MODEL_API_KEY') or os.getenv('OPENAI_API_KEY')) or not all(models.values()):
        raise ValueError('Нужны MODEL_API_KEY (или OPENAI_API_KEY), WORKER_MODEL, JUDGE_MODEL, CLIENT_MODEL. См. README.md.')
    if models['worker']==models['judge']:
        raise ValueError('PRO требует отдельную сильную модель-судью и более дешевую рабочую модель.')
    out = Path(args.output) if args.output else ROOT/'results'/datetime.now(timezone.utc).strftime('pro-%Y%m%dT%H%M%S%fZ')
    out.mkdir(parents=True,exist_ok=False)
    client = ModelClient(out/'calls.jsonl',args.max_calls)
    versions = {'recruiter':[prompt('recruiter')], 'sales':[prompt('sales')]}
    vacancy = (ROOT/'data/vacancy.txt').read_text()
    manifest = {**plan,'models':models,'status':'running','started_at':datetime.now(timezone.utc).isoformat(),
                'api_style':os.getenv('API_STYLE','responses'),'api_base_url':os.getenv('API_BASE_URL','https://api.openai.com/v1'),
                'json_mode':os.getenv('JSON_MODE','json_schema'),
                'dataset_hashes':{name:digest((ROOT/'data'/name).read_text()) for name in ['resumes.json','scenarios.json','product.json','vacancy.txt']}}
    write_json(out/'manifest.json',manifest)
    write_json(out/'datasets/resumes.json',resumes); write_json(out/'datasets/scenarios.json',scenarios)
    write_json(out/'datasets/product.json',read_json(ROOT/'data/product.json'))
    (out/'datasets/vacancy.txt').write_text(vacancy)
    (out/'reference_prompt.txt').write_text(prompt('recruiter'))
    from pro.evaluate import JUDGE_PROMPT
    (out/'sales_judge_prompt.txt').write_text(JUDGE_PROMPT)
    references = {}
    summary = {'iterations':[], 'selected':{}, 'holdout':{}}
    try:
        for case in resumes:
            references[case['id']] = recruit(client,models['judge'],vacancy,case['resume'],
                instructions=prompt('recruiter')+'\nПрименяй фиксированную рубрику особенно внимательно; это эталон для сравнения, а не абсолютная истина.',tag='reference/'+case['id'])
            write_json(out/'references'/f"{case['id']}.json",references[case['id']])
        for i in range(args.iterations):
            item = {'version':i+1}
            for agent,dataset in [('recruiter',resumes),('sales',scenarios)]:
                current = versions[agent][i]
                p = out/'prompts'/f'{agent}_v{i+1}.txt'; p.parent.mkdir(exist_ok=True); p.write_text(current)
                training = None
                for split in ['train','validation']:
                    rows = evaluate(client,models,agent,[c for c in dataset if c['split']==split],current, references,vacancy,args.turns,out,f'v{i+1}/{agent}/{split}')
                    item[f'{agent}_{split}'] = (recruiter_metrics if agent=='recruiter' else sales_metrics)(rows)
                    if split == 'train': training = rows
                if i+1 < args.iterations:
                    change = optimize(client,models['judge'],agent,current,training,f'optimize/{agent}/v{i+2}')
                    if not change['prompt'].strip(): raise ValueError('Оптимизатор вернул пустой промпт')
                    write_json(out/'changes'/f'{agent}_v{i+2}.json',change)
                    versions[agent].append(change['prompt'])
            summary['iterations'].append(item)
            write_json(out/'summary.json',summary)
            print(f'Итерация {i+1} сохранена; запросов {client.calls}',flush=True)
        for agent,dataset in [('recruiter',resumes),('sales',scenarios)]:
            def rank(item):
                metric = item[agent+'_validation']
                return (metric['contract_error_rate'],metric['score_mae'],-metric['verdict_accuracy']) if agent=='recruiter' else (metric['hallucination_rate'],-metric['mean_score'])
            best = min(summary['iterations'],key=rank)['version']
            summary['selected'][agent] = best
            # Freeze selection before opening holdout; compare first and last as assignment requires.
            write_json(out/'selection.json',summary['selected'])
            holdout = [c for c in dataset if c['split']=='holdout']
            for i in [0,args.iterations-1]:
                rows = evaluate(client,models,agent,holdout,versions[agent][i],references,vacancy,args.turns,out,f'holdout/{agent}/v{i+1}')
                summary['holdout'][f'{agent}_v{i+1}'] = (recruiter_metrics if agent=='recruiter' else sales_metrics)(rows)
        manifest['status'] = 'completed'
        write_json(out/'summary.json',summary)
        report(out,summary,manifest,client.calls)
    except Exception as exc:
        manifest['status']='failed'; manifest['error']=str(exc)
        raise
    finally:
        manifest['actual_requests']=client.calls
        manifest['finished_at']=datetime.now(timezone.utc).isoformat()
        write_json(out/'manifest.json',manifest)
        print('Результаты: '+str(out),flush=True)


def evaluate(client,models,agent,cases,instructions,references,vacancy,turns,out,prefix):
    rows = []
    for case in cases:
        tag = prefix+'/'+case['id']
        if agent=='recruiter':
            answer = recruit(client,models['worker'],vacancy,case['resume'],instructions,tag,strict=False)
            row = {'id':case['id'],'resume':case['resume'],'answer':answer,'reference':references[case['id']], 'issues':recruit_checks(answer,case['resume'])}
        else:
            row = simulate(client,models['worker'],models['client'],models['judge'],case,instructions,turns,tag)
        rows.append(row)
        write_json(out/'evaluations'/f'{tag}.json',row)
    return rows


def report(out,summary,manifest,calls):
    last = manifest['iterations']
    lines = ['# Результаты PRO','',f"Режим: {manifest['mode']}. Фактических запросов: {calls}.",'',
        'Эталон — оценка сильной модели по фиксированной рубрике, а не объективная истина. Выбор версии сделан на validation. Holdout не использовался для улучшения промптов.', '',
        '| Агент | Метрика holdout | Первая версия | Последняя версия | Изменение |','|---|---|---:|---:|---:|']
    for agent in ['recruiter','sales']:
        first = summary['holdout'][agent+'_v1']; final = summary['holdout'][f'{agent}_v{last}']
        for key in first:
            if key != 'count':
                lines.append(f"| {agent} | {key} | {first[key]} | {final[key]} | {round(final[key]-first[key],3):+} |")
    lines += ['', 'Меньше — лучше: score_mae, criteria_mae, contract_error_rate, hallucination_rate. Больше — лучше: verdict_accuracy и оценки продавца.', '', '## Что улучшилось и что осталось', '']
    for agent in ['recruiter','sales']:
        first=summary['holdout'][agent+'_v1']; final=summary['holdout'][f'{agent}_v{last}']
        key='score_mae' if agent=='recruiter' else 'mean_score'
        improved=final[key]<first[key] if agent=='recruiter' else final[key]>first[key]
        lines.append(f"- {agent}: {'улучшение' if improved else 'улучшение не подтверждено'} по {key}; выбрана версия {summary['selected'][agent]} по validation.")
    lines += ['', '## Сохранившиеся ошибки последней версии', '']
    for agent in ['recruiter','sales']:
        rows=[read_json(p) for p in (out/'evaluations/holdout'/agent/f'v{last}').glob('*.json')]
        if agent=='recruiter':
            rows.sort(key=lambda r:abs(r['answer']['score']-r['reference']['score']),reverse=True)
            for r in rows[:5]:
                lines.append(f"- {r['id']}: балл {r['answer']['score']}, эталон {r['reference']['score']}; нарушения: {', '.join(r['issues']) or 'нет формальных нарушений'}.")
        else:
            for r in rows:
                for error in r['assessment']['errors']:
                    lines.append(f"- {r['id']}: {error}")
    lines += ['', '## Ограничения', '',
        'Данные синтетические. На каждого клиента выполнен один стохастический диалог на версию: одинаковы сценарии и начальные реплики, но последующие реплики клиента зависят от ответов продавца. Это парное сравнение сценариев, а не идентичных транскриптов. Для устойчивых выводов нужны повторные прогоны с несколькими случайными реализациями и человеческая проверка эталонов. Формальная проверка цитат не обнаруживает все смысловые ошибки.', '',
        'Журнал calls.jsonl содержит запросы, ответы, usage и длительность. Ошибочные попытки входят в счетчик. Автоматических повторов нет. Файлы changes содержат объяснения изменений, prompts — полные версии.']
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--iterations',type=int,default=2)
    parser.add_argument('--turns',type=int,default=4)
    parser.add_argument('--max-calls',type=int,default=1000)
    parser.add_argument('--smoke',action='store_true')
    parser.add_argument('--plan',action='store_true')
    parser.add_argument('--output')
    args=parser.parse_args()
    if args.iterations<2 or args.turns<1: parser.error('Нужно минимум 2 итерации и 1 ход')
    run(args)

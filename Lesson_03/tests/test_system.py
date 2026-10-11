import argparse
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from lite.core import ROOT, CRITERIA, RECRUIT_SCHEMA, ModelClient, validate, recruit_checks, read_json
from pro.run import run

def answer():
    return {'score':0,'criteria':[{'key':key,'points':0,'max_points':maximum,'reason':'Тест','evidence':[],'missing':[]} for key,maximum in CRITERIA.items()], 'strengths':[], 'gaps':[], 'missing_information':[], 'verdict':'insufficient_evidence','conclusion':'Тестовый ответ, не оценка AI'}

class FakeClient:
    instances=[]
    def __init__(self,*args,**kwargs):
        self.calls=0;self.records=[];self.instances.append(self)
    def ask(self,model,instructions,messages,schema,tag):
        self.calls+=1;self.records.append((tag,messages))
        fields=schema['properties']
        if 'criteria' in fields:return answer()
        if 'typical_errors' in fields:return {'typical_errors':['Тест'],'changes':['Тест'],'prompt':'Тестовый промпт версии 2'}
        if 'needs' in fields:return {'needs':1,'presentation':1,'objections':1,'truthfulness':1,'next_step':1,'invented_conditions':[],'errors':['Тестовая ошибка'],'explanation':'Тест'}
        if 'known_needs' in fields:return {'message':'Тестовая реплика','known_needs':[],'unknown_conditions':[],'next_step':''}
        return {'message':'Тестовый клиент'}

class Tests(unittest.TestCase):
    def test_real_response_rejects_communication_three(self):
        result = read_json(ROOT/'tests/fixtures/recruiter-invalid-scale.json')
        resume = read_json(ROOT/'data/lite_cases.json')['recruiter'][1]['resume']
        validate(result, RECRUIT_SCHEMA)
        self.assertTrue(any('communication' in issue for issue in recruit_checks(result, resume)))

    def test_dataset_sizes_disjoint_and_diverse(self):
        for name,count,split_counts in [('resumes.json',100,{'train':60,'validation':20,'holdout':20}),('scenarios.json',30,{'train':18,'validation':6,'holdout':6})]:
            rows=read_json(ROOT/'data'/name)
            self.assertEqual(len(rows),count)
            self.assertEqual(len({r['id'] for r in rows}),count)
            for split,n in split_counts.items():self.assertEqual(sum(r['split']==split for r in rows),n)
        self.assertEqual(len({r['resume'] for r in read_json(ROOT/'data/resumes.json')}),100)

    def test_valid_response_and_false_quotes(self):
        result=answer();validate(result,RECRUIT_SCHEMA)
        self.assertEqual(recruit_checks(result,'Python'),[])
        result['criteria'][0]['evidence']=['SQL']
        self.assertTrue(any('Цитата' in s for s in recruit_checks(result,'Python')))

    def test_total_threshold_duplicate_and_overflow(self):
        result=answer();result['score']=85
        self.assertEqual(len(recruit_checks(result,'')),2)
        result=answer();result['criteria'][0]['points']=41
        self.assertTrue(recruit_checks(result,''))
        result=answer();result['criteria'][1]=result['criteria'][0].copy()
        self.assertTrue(recruit_checks(result,''))

    def test_strict_types_and_extra_keys(self):
        result=answer();result['score']=True
        with self.assertRaises(ValueError):validate(result,RECRUIT_SCHEMA)
        result=answer();result['extra']='bad'
        with self.assertRaises(ValueError):validate(result,RECRUIT_SCHEMA)

    def test_missing_key_makes_no_calls(self):
        with patch.dict(os.environ,{},clear=True):
            client=ModelClient()
            with self.assertRaises(RuntimeError):client.ask('test','',[],RECRUIT_SCHEMA,'test')
            self.assertEqual(client.calls,0)

    def test_transport_and_no_key_in_log(self):
        for style in ['responses','chat_completions']:
            with self.subTest(style=style), tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,{'MODEL_API_KEY':'test-secret','API_STYLE':style},clear=True):
                raw={'status':'completed','output':[{'content':[{'type':'output_text','text':json.dumps(answer())}]}]} if style=='responses' else {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer())}}]}
                log=Path(temp)/'calls.jsonl';client=ModelClient(log,max_calls=1)
                with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(raw).encode())):
                    self.assertEqual(client.ask('model','prompt',[],RECRUIT_SCHEMA,'test'),answer())
                self.assertNotIn('test-secret',log.read_text())
                self.assertEqual(client.calls,1)
                with self.assertRaises(RuntimeError):client.ask('model','prompt',[],RECRUIT_SCHEMA,'test')

    def test_incomplete_response_logged_as_failure(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,{'MODEL_API_KEY':'test','API_STYLE':'responses'},clear=True):
            log=Path(temp)/'log.jsonl';client=ModelClient(log)
            with patch('urllib.request.urlopen',return_value=io.BytesIO(b'{"status":"incomplete"}')):
                with self.assertRaises(RuntimeError):client.ask('m','',[],RECRUIT_SCHEMA,'test')
            self.assertIn('error',read_json(log))

    def test_complete_pro_pipeline_fake_and_no_holdout_in_optimizer(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,{'MODEL_API_KEY':'fake','WORKER_MODEL':'worker','JUDGE_MODEL':'judge','CLIENT_MODEL':'client'}), patch('pro.run.ModelClient',FakeClient),contextlib.redirect_stdout(io.StringIO()):
            out=Path(temp)/'run'
            run(argparse.Namespace(smoke=True,iterations=2,turns=2,max_calls=100,plan=False,output=str(out)))
            manifest=read_json(out/'manifest.json')
            self.assertEqual(manifest['status'],'completed')
            self.assertEqual(manifest['actual_requests'],manifest['planned_requests'])
            self.assertTrue((out/'REPORT.md').exists())
            self.assertEqual(len(read_json(out/'summary.json')['holdout']),4)
            holdouts=[r['id'] for r in read_json(ROOT/'data/resumes.json')+read_json(ROOT/'data/scenarios.json') if r['split']=='holdout']
            for tag,messages in FakeClient.instances[-1].records:
                if tag.startswith('optimize/'):
                    value=json.loads(messages[0]['content'])
                    self.assertTrue(all(r['id'] not in holdouts for r in value['training_examples']))

    def test_failed_run_preserves_manifest(self):
        class Broken(FakeClient):
            def ask(self,*args,**kwargs):self.calls+=1;raise RuntimeError('Test failure')
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'MODEL_API_KEY':'fake','WORKER_MODEL':'worker','JUDGE_MODEL':'judge','CLIENT_MODEL':'client'}),patch('pro.run.ModelClient',Broken),contextlib.redirect_stdout(io.StringIO()):
            out=Path(temp)/'run'
            with self.assertRaises(RuntimeError):run(argparse.Namespace(smoke=True,iterations=2,turns=2,max_calls=100,plan=False,output=str(out)))
            self.assertEqual(read_json(out/'manifest.json')['status'],'failed')

if __name__=='__main__':unittest.main()

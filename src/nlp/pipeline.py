"""Sentiment pipeline. ONNX primary, PyTorch fallback."""
from __future__ import annotations
import json,logging,os
from dataclasses import dataclass,field
from enum import Enum
from pathlib import Path
import numpy as np
from src.config import settings
logger=logging.getLogger(__name__)
class Sentiment(str,Enum):
    POSITIVE="positive";NEGATIVE="negative";NEUTRAL="neutral";MIXED="mixed"
@dataclass
class SentimentResult:
    text:str;sentiment:Sentiment;confidence:float;language:str;model_used:str
    aspects:list[dict]=field(default_factory=list);sarcasm_detected:bool=False
    sarcasm_confidence:float=0.0;explanation:str="";raw_scores:dict[str,float]=field(default_factory=dict)
class SentimentPipeline:
    def __init__(self):
        self.tokenizer=None;self.session=None;self.pt_model=None
        self.id2label={0:"negative",1:"neutral",2:"positive"}
        self.l2s={"positive":Sentiment.POSITIVE,"negative":Sentiment.NEGATIVE,"neutral":Sentiment.NEUTRAL,"mixed":Sentiment.MIXED}
        self._init=False
    def initialize(self):
        if self._init: return
        logger.info(f"Loading model dari {settings.nlp_model_path}...")
        self._load();self._init=True;logger.info("Pipeline siap")
    def _load(self):
        mp=Path(settings.nlp_model_path);onnx_f=mp/"model.onnx"
        if onnx_f.exists():
            try:
                import onnxruntime as ort;o=ort.SessionOptions();o.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_ALL;o.intra_op_num_threads=os.cpu_count() or 4
                pr=["CPUExecutionProvider"]
                if settings.nlp_device=="cuda": pr.insert(0,"CUDAExecutionProvider")
                self.session=ort.InferenceSession(str(onnx_f),o,providers=pr);logger.info("ONNX loaded")
            except ImportError: logger.warning("onnxruntime tidak ada, fallback PyTorch")
        cf=mp/"config.json"
        if cf.exists():
            with open(cf) as f: cfg=json.load(f)
            if "id2label" in cfg:
                self.id2label={int(k):v for k,v in cfg["id2label"].items()}
                for k,v in self.id2label.items():
                    vl=v.lower()
                    if "positive" in vl or "pos" in vl: self.id2label[k]="positive"
                    elif "negative" in vl or "neg" in vl: self.id2label[k]="negative"
                    else: self.id2label[k]="neutral"
        if self.session is None: self._load_pt(mp)
        from transformers import AutoTokenizer;self.tokenizer=AutoTokenizer.from_pretrained(str(mp))
    def _load_pt(self,mp):
        import torch;from transformers import AutoModelForSequenceClassification
        self.pt_model=AutoModelForSequenceClassification.from_pretrained(str(mp))
        if settings.nlp_device=="cuda" and torch.cuda.is_available(): self.pt_model=self.pt_model.cuda()
        self.pt_model.eval();logger.info("PyTorch loaded")
    def analyze(self,text):
        self.initialize();clean=self._preprocess(text)
        if not clean or len(clean)<10: return self._neut(text,"short")
        lang=self._lang(clean);s,c,sc=self._predict(clean);mu="indobert-onnx" if self.session else "indobert-pytorch";expl=""
        if c<settings.nlp_confidence_threshold and settings.has_llm:
            lr=self._llm(clean,lang)
            if lr: s,c,expl=lr["sentiment"],lr["confidence"],lr["explanation"];mu+="+llm"
        return SentimentResult(text=text,sentiment=s,confidence=round(c,4),language=lang,model_used=mu,explanation=expl,raw_scores=sc)
    def _predict(self,text):
        inp=self.tokenizer(text,return_tensors="np",truncation=True,max_length=settings.nlp_max_text_length,padding="max_length")
        if self.session:
            names=[i.name for i in self.session.get_inputs()]
            oi={"input_ids":inp["input_ids"].astype(np.int64),"attention_mask":inp["attention_mask"].astype(np.int64)}
            if "token_type_ids" in names: oi["token_type_ids"]=inp.get("token_type_ids",np.zeros_like(inp["input_ids"])).astype(np.int64)
            out=self.session.run(None,oi)[0];probs=self._sm(out[0])
        else:
            import torch
            with torch.no_grad():
                ids=torch.tensor(inp["input_ids"]);mk=torch.tensor(inp["attention_mask"])  
                if settings.nlp_device=="cuda": ids,mk=ids.cuda(),mk.cuda()
                o=self.pt_model(input_ids=ids,attention_mask=mk);probs=self._sm(o.logits.cpu().numpy()[0])
        scores={self.id2label.get(i,f"l{i}"):round(float(p),4) for i,p in enumerate(probs)}
        ti=int(np.argmax(probs));tl=self.id2label.get(ti,"neutral")
        return self.l2s.get(tl,Sentiment.NEUTRAL),float(probs[ti]),scores
    def _llm(self,text,lang):
        try:
            from openai import OpenAI;from src.nlp.prompts import SENTIMENT_SYS
            c=OpenAI(api_key=settings.openai_api_key)
            r=c.chat.completions.create(model=settings.openai_model,response_format={"type":"json_object"},messages=[{"role":"system","content":SENTIMENT_SYS},{"role":"user","content":f"Bahasa:{lang}\n\n{text[:2000]}"}],temperature=0.1,max_tokens=settings.llm_max_tokens)
            d=json.loads(r.choices[0].message.content)
            return {"sentiment":self.l2s.get(d.get("sentiment","neutral"),Sentiment.NEUTRAL),"confidence":float(d.get("confidence",0.5)),"explanation":d.get("explanation","")}
        except Exception as e: logger.error(f"LLM gagal:{e}");return None
    @staticmethod
    def _sm(x): e=np.exp(x-np.max(x));return e/e.sum()
    @staticmethod
    def _lang(t):
        try: from langdetect import detect;return detect(t[:500])
        except: return "id"
    @staticmethod
    def _preprocess(t):
        import re;t=re.sub(r"<[^>]+>"," ",t);t=re.sub(r"https?://\S+","",t);return re.sub(r"\s+"," ",t).strip()
    @staticmethod
    def _neut(t,r): return SentimentResult(text=t,sentiment=Sentiment.NEUTRAL,confidence=0.0,language="unknown",model_used=r)
_p=None
def get_pipeline():
    global _p
    if _p is None: _p=SentimentPipeline();_p.initialize()
    return _p
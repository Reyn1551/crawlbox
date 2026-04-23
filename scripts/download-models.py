"""Download IndoBERT + export ONNX."""
import sys
from pathlib import Path
def main():
    print("="*50+"\nSentimentTools — Model Download\n"+"="*50)
    model_name="mdhugol/indonesia-sentiment";save_path=Path("./models/indobert-sentiment");save_path.mkdir(parents=True,exist_ok=True)
    print(f"\n[1/2] Download: {model_name}")
    try:
        from transformers import AutoModelForSequenceClassification,AutoTokenizer
        tok=AutoTokenizer.from_pretrained(model_name);mdl=AutoModelForSequenceClassification.from_pretrained(model_name)
        tok.save_pretrained(save_path);mdl.save_pretrained(save_path);print(f"  Saved: {save_path}")
    except Exception as e:print(f"  Gagal: {e}");sys.exit(1)
    print("\n[2/2] Export ONNX...")
    try:
        import torch;dummy=tok("Contoh teks",return_tensors="pt");has_tti="token_type_ids" in dummy
        args=(dummy["input_ids"],dummy["attention_mask"])
        if has_tti:args=args+(dummy["token_type_ids"],)
        names=["input_ids","attention_mask"]
        if has_tti:names.append("token_type_ids")
        da={n:{0:"batch",1:"seq"} for n in names};da["logits"]={0:"batch"}
        torch.onnx.export(mdl,args,str(save_path/"model.onnx"),input_names=names,output_names=["logits"],dynamic_axes=da,opset_version=14);print(f"  ONNX: {save_path/'model.onnx'}")
    except ImportError:print("  skip ONNX (onnxruntime/torch tidak ada)")
    except Exception as e:print(f"  ONNX gagal: {e}")
    print("\n"+"="*50+"\nSelesai! python -m src.main\n"+"="*50)
if __name__=="__main__":main()
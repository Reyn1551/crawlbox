SENTIMENT_SYS = """Kamu analis sentimen expert Indonesia.
Output JSON: {"sentiment":"positive|negative|neutral|mixed","confidence":0.0-1.0,"explanation":"..."}"""
ABSA_PROMPT = 'Dari teks, identifikasi aspek dan sentimen.\nOutput: {"aspects":[{"aspect":"...","sentiment":"positive|negative|neutral","snippet":"..."}]}\nTeks: {text}'
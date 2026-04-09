import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
tokens = os.getenv("GEMINI_TOKENS", os.getenv("GEMINI_TOKEN", "")).split(",")

for i, token in enumerate(tokens):
    print(f"\n--- Checking Token {i} ---")
    try:
        genai.configure(api_key=token.strip())
        models = genai.list_models()
        for m in models:
            if 'generateContent' in m.supported_generation_methods:
                print(f"Name: {m.name} | Display Name: {m.display_name}")
    except Exception as e:
        print(f"Error for token {i}: {e}")

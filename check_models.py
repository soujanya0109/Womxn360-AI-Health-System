import google.generativeai as genai

# !!! PASTE YOUR API KEY BELOW !!!
genai.configure(api_key="AIzaSyBjm8QSK8c57lVjCl6fHkrQkXvfe4k04Pk")

print("--- Contacting Google... ---")
try:
    # List all models available to your specific API Key
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"✅ AVAILABLE: {m.name}")

except Exception as e:
    print(f"❌ Error: {e}")
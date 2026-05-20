from google import genai
from google.genai import types
import os

os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = 'True'
os.environ['GOOGLE_CLOUD_PROJECT'] = 'GOOGLE_CLOUD_PROJECT'
os.environ['GOOGLE_CLOUD_LOCATION'] = 'global'

# 检查可用的配置类
print("GenerateContentConfig attributes:")
print([attr for attr in dir(types.GenerateContentConfig) if not attr.startswith('_')])

print("\nGenerateImageConfig exists:", hasattr(types, 'GenerateImageConfig'))
if hasattr(types, 'GenerateImageConfig'):
    print("GenerateImageConfig attributes:")
    print([attr for attr in dir(types.GenerateImageConfig) if not attr.startswith('_')])

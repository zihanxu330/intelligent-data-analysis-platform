import os
from dotenv import load_dotenv
load_dotenv()
ITICK_TOKEN=os.getenv('ITICK_TOKEN') or os.getenv('ITICK_API_KEY')
DATABASE={
'host':os.getenv('DB_HOST','localhost'),
'port':int(os.getenv('DB_PORT','3307')),
'user':os.getenv('DB_USER','root'),
'password':os.getenv('DB_PASSWORD',''),
'database':os.getenv('DB_NAME','quant_ai')}
MODEL_PATH=os.getenv('MODEL_PATH','output/')

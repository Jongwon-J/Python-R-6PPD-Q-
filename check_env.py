from dotenv import load_dotenv
import os

load_dotenv()
print(repr(os.getenv('ADMIN_TOKEN')))
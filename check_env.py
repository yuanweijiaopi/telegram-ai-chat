from dotenv import load_dotenv
import os
load_dotenv()
print(repr(os.getenv('CHARACTER_XIAOMING_PHONE')))
print(repr(os.getenv('CHARACTER_LAOWANG_PHONE')))

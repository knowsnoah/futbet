import os
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Get URI from environment
uri = os.getenv("MONGO_URI")

client = None
if uri:
    try:
        # Create Mongo client
        client = MongoClient(uri, server_api=ServerApi('1'), serverSelectionTimeoutMS=5000)
        # Test connection
        client.admin.command('ping')
        print("Pinged your deployment. You successfully connected to MongoDB!")
    except Exception as e:
        print(f"MongoDB connection failed: {e}")
        client = None
else:
    print("MONGO_URI not found in .env file")


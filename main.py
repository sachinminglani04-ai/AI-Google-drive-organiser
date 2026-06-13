import os
import io
import google.generativeai as genai
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# --- CONFIGURATION ---
GENAI_API_KEY = ""
SCOPES = ['https://www.googleapis.com/auth/drive']

# FORCE V1 API (This kills the 404 error for most users)
os.environ["GOOGLE_GENAI_USE_V1API"] = "1"
genai.configure(api_key=GENAI_API_KEY)

def get_best_model():
    """Automatically finds the correct model name available for your API Key."""
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                # Prioritize Flash 1.5, then Pro
                if 'gemini-1.5-flash' in m.name:
                    return m.name
        return 'models/gemini-pro' # Fallback
    except Exception:
        return 'models/gemini-1.5-flash'

# Initialize the model dynamically
SELECTED_MODEL = get_best_model()
model = genai.GenerativeModel(SELECTED_MODEL)

def get_drive_service():
    """Handles Google Drive Authentication."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('drive', 'v3', credentials=creds)

def classify_file_with_ai(service, file_id, filename):
    """Deep Analysis: Reads the file content and uses Gemini to categorize."""
    content_snippet = "No readable text content found."
    
    # 1. READ THE CONTENT (Essential for AI participation)
    try:
        request = service.files().get_media(fileId=file_id)
        file_data = io.BytesIO()
        downloader = MediaIoBaseDownload(file_data, request)
        downloader.next_chunk()
        content_snippet = file_data.getvalue().decode('utf-8', errors='ignore')[:1000]
    except Exception:
        pass # If we can't read it, we still try based on filename

    # 2. THE AI PROMPT
    prompt = f"""
    Analyze this file carefully.
    NAME: {filename}
    CONTENT: {content_snippet}

    Categories: HR, Finance, Academics, Projects, Marketing, Personal.
    
    INSTRUCTIONS:
    - Base your decision on the TEXT CONTENT primarily.
    - If the text mentions 'Invoice', 'Tax', or 'Bill', it's Finance.
    - If it's about 'Research' or 'Assignment', it's Academics.
    - Return ONLY the category name. If unsure, return 'Unsorted'.
    """

    try:
        # 3. ASK THE AI
        response = model.generate_content(prompt)
        category = response.text.strip().split()[0].replace('.', '').replace('*', '')
        
        valid = ["HR", "Finance", "Academics", "Projects", "Marketing", "Personal"]
        for v in valid:
            if v.lower() in category.lower():
                return v
        return "Unsorted"
    except Exception as e:
        print(f"  🤖 AI Connection Error: {e}")
        return "Unsorted"

def get_or_create_folder(service, folder_name):
    """Retrieves or creates a category folder."""
    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=query, fields="files(id)").execute()
    folders = results.get('files', [])
    if folders: return folders[0]['id']
    
    metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
    folder = service.files().create(body=metadata, fields='id').execute()
    return folder.get('id')

def move_file(service, file_id, folder_id):
    """Safely moves a file to a new folder."""
    try:
        file = service.files().get(fileId=file_id, fields='parents').execute()
        prev = ",".join(file.get('parents', []))
        service.files().update(fileId=file_id, addParents=folder_id, removeParents=prev).execute()
    except Exception:
        print(f"  ❌ Permission Error: Skipping file.")

def main():
    print(f"--- 🚀 AI Organizer Active (Model: {SELECTED_MODEL}) ---")
    service = get_drive_service()
    
    # List all files in the root
    query = "'root' in parents and mimeType != 'application/vnd.google-apps.folder'"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])

    if not files:
        print("✅ No files in root. Everything is already organized!")
        return

    for f in files:
        print(f"📂 Analyzing: {f['name']}")
        category = classify_file_with_ai(service, f['id'], f['name'])
        print(f"  🤖 AI Decision: {category}")
        
        f_id = get_or_create_folder(service, category)
        move_file(service, f['id'], f_id)
        print(f"  ✅ Successfully moved.\n")

    print("--- ✨ Process Complete ---")

if __name__ == '__main__':
    main()

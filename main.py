from fastapi import APIRouter, UploadFile, File, HTTPException, status, Form, FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from firebase_admin import credentials, firestore, initialize_app
import requests
import os
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime
from config.cloudinary import *
from cloudinary.uploader import upload
import json
from typing import List

router = APIRouter()
load_dotenv()

# Initialize Firebase
cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if not cred_path:
    raise ValueError("GOOGLE_APPLICATION_CREDENTIALS environment variable not set.")

cred_path = Path(cred_path).expanduser().resolve()
if not cred_path.is_file():
    raise FileNotFoundError(f"Firebase credential file not found: {cred_path}")

cred = credentials.Certificate(str(cred_path))
initialize_app(cred)
db = firestore.client()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class PostData(BaseModel):
    title: str
    content: str
    author_uid: str
    post_type: str
    image_url: str = None

class AuthRequest(BaseModel):
    email: str
    password: str
    username: str | None = None   # ✅ allow username during signup

# Use the correct API key from your Firebase project settings
FIREBASE_API_KEY = os.environ.get("FIREBASE_WEB_API_KEY")
if not FIREBASE_API_KEY:
    raise ValueError("FIREBASE_WEB_API_KEY environment variable not set.")

@app.post("/signup")
def signup(request: AuthRequest):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FIREBASE_API_KEY}"
    payload = {
        "email": request.email,
        "password": request.password,
        "returnSecureToken": True
    }
    resp = requests.post(url, json=payload)
    if resp.status_code == 200:
        data = resp.json()
        # ✅ save username + email in Firestore under localId
        db.collection("users").document(data["localId"]).set({
            "username": request.username,
            "email": request.email,
            "created_at": datetime.now()
        })
        # also return username so frontend can use it
        data["username"] = request.username
        return data
    else:
        raise HTTPException(
            status_code=400,
            detail=resp.json().get("error", {}).get("message", "Signup failed")
        )

@app.post("/login")
def login(request: AuthRequest):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
    payload = {
        "email": request.email,
        "password": request.password,
        "returnSecureToken": True
    }
    resp = requests.post(url, json=payload)
    if resp.status_code == 200:
        data = resp.json()
        # ✅ fetch username from Firestore
        user_doc = db.collection("users").document(data["localId"]).get()
        if user_doc.exists:
            data["username"] = user_doc.to_dict().get("username")
        return data
    else:
        raise HTTPException(status_code=401, detail="Invalid credentials")

@app.post("/posts")
def create_post(
    title: str = Form(...),
    content: str = Form(...),
    author_uid: str = Form(...),
    post_type: str = Form(...),
    files: List[UploadFile] = File(None),
    tags: str = Form("[]") # to accept the tags
):
    try:
        # get username from Firestore
        user_doc = db.collection("users").document(author_uid).get()
        username = None
        if user_doc.exists:
            username = user_doc.to_dict().get("username")

        # Handle file upload if a file exists
        file_urls = []
        if files:
            for file in files:
                if file and file.filename:
                    upload_result = upload(file.file, resource_type="auto")
                    file_urls.append(upload_result.get("secure_url"))
            
        # Parse tags from the JSON string
        try:
            parsed_tags = json.loads(tags)
        except json.JSONDecodeError:
            parsed_tags = []

        post_data = {
            "title": title,
            "content": content,
            "author_uid": author_uid,
            "author": username,
            "type": post_type,
            "timestamp": datetime.now(),
            "file_urls": file_urls,   # ⬅ list of URLs instead of single
            "tags": parsed_tags # Store the parsed tags
        }

        db.collection("posts").add(post_data)
        return {"message": "Post created successfully", "post_data": post_data}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {e}")



@app.get("/users/{user_uid}/posts")
def get_user_posts(user_uid: str):
    try:
        posts_ref = db.collection("posts")
        query = posts_ref.where("author_uid", "==", user_uid)
        docs = query.stream()
        posts = []
        for doc in docs:
            post_data = doc.to_dict()
            post_data["id"] = doc.id
            posts.append(post_data)

        return {"posts": posts}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred: {e}"
        )

    
    
@app.get("/posts")
async def get_all_posts():
    docs = db.collection("posts").stream()
    posts = []
    user_ids = set()

    # Step 1: Collect all unique user IDs from the posts
   

    # Step 2: Fetch all user data in a single batch
    users = {}
    if user_ids:
        users_query = db.collection("users").where(firestore.FieldPath.document_id(), "in", list(user_ids)).stream()
        for user_doc in users_query:
            users[user_doc.id] = user_doc.to_dict()

    # Step 3: Add the author's name to each post
    for post in posts:
        user_id = post.get("user_id")
        author_name = users.get(user_id, {}).get("displayName", "Anonymous")
        post["author"] = author_name
    
    


    all_comments_query = db.collection("comments").order_by("timestamp").stream()
    all_comments = {}
    for comment in all_comments_query:
        post_id = comment.to_dict()["post_id"]
        if post_id not in all_comments:
            all_comments[post_id] = []
        all_comments[post_id].append(comment.to_dict())

    # Now, process each post once and attach the pre-fetched data
    for doc in docs:
        post_data = doc.to_dict()
        post_id = doc.id
        post_data["id"] = post_id
        user_ids.add(post_data.get("user_id"))
        post_data["likes_count"] = post_data.get("likes_count", 0)
        post_data["comments"] = all_comments.get(post_id, [])
        
        posts.append(post_data)
        
    return posts

# 🔑 Correct the like endpoint to get user_id from the JSON body
from fastapi import APIRouter
from firebase_admin import firestore
from firebase_admin.firestore import firestore
from pydantic import BaseModel

# ... (app and db initialization from your previous code)

class UserLike(BaseModel):
    user_id: str

@app.post("/posts/{post_id}/like")
async def like_post(post_id: str, like_data: UserLike):
    post_ref = db.collection("posts").document(post_id)

    # Add a print statement to verify the post_id
    print(f"Received request to like post: {post_id}")
    
    # Use a transaction for the update
    @firestore.transactional
    def update_likes_count(transaction, post_ref, user_id):
        # Retrieve the document to check its current state
        post_snapshot = post_ref.get(transaction=transaction)
        
        # Add a print statement to see the document's content
        print(f"Before update, post data: {post_snapshot.to_dict()}")

        # Check if the likes_count field exists and is a number
        # If not, initialize it to 0
        if not post_snapshot.exists or not isinstance(post_snapshot.to_dict().get("likes_count"), (int, float)):
            transaction.set(post_ref, {"likes_count": 0}, merge=True)
            
        # Atomically increment the likes_count field by 1
        transaction.update(post_ref, {"likes_count": firestore.Increment(1)})

    transaction = db.transaction()
    update_likes_count(transaction, post_ref, like_data.user_id)
    
    # After the transaction, fetch the post to get the new count
    updated_post = post_ref.get().to_dict()
    new_likes_count = updated_post.get("likes_count", 0)

    # Add a final print statement to show the new value
    print(f"After update, new likes count for {post_id} is: {new_likes_count}")
    
    return {"message": "Post liked successfully", "likes": new_likes_count}
@app.post("/posts/{post_id}/comment")
async def post_comment(post_id: str, user_id: str = Body(..., embed=True), text: str = Body(..., embed=True)):
    """Adds a comment to a post. Requires user_id."""
    # Fetch username from Firestore
    user_doc = db.collection("users").document(user_id).get()
    username = user_doc.to_dict().get("username") if user_doc.exists else "Unknown"
    comment_data = {
        "post_id": post_id,
        "user_id": user_id,
        "username": username,  # <-- Store username
        "text": text,
        "timestamp": firestore.SERVER_TIMESTAMP
    }
    db.collection("comments").add(comment_data)
    return {"message": "Comment posted successfully"}

@app.get("/posts/{post_id}")
def get_post(post_id: str):
    print(f"Fetching post with ID: {post_id}")  # Debug print
    # db = firestore.client()  # ❌ REMOVE THIS LINE
    post_ref = db.collection("posts").document(post_id)
    post = post_ref.get()
    print(f"Post exists: {post.exists}")  # Debug print
    if not post.exists:
        raise HTTPException(status_code=404, detail="Post not found")
    post_data = post.to_dict()
    post_data["id"] = post_id

    # Fetch comments for this post
    comments_ref = db.collection("comments").where("post_id", "==", post_id).stream()
    post_data["comments"] = [c.to_dict() for c in comments_ref]

    return post_data
from pydantic import BaseModel, Field
from typing import Optional, List

# This is the data model for the post data sent from the frontend to the backend.
# It should match the data sent by the "CreateBlogPage" component in App.jsx.
class PostData(BaseModel):
    title: str
    content: str
    author_uid: str
    post_type: str
    file_url: Optional[str] = None
    tags: Optional[List[str]] = []

# This model is used by the signup/login endpoints.
class AuthRequest(BaseModel):
    email: str
    password: str
    username: Optional[str] = None

# This model is likely used for reading posts from Firestore.
# The backend doesn't need to define this, but it's good to have for clarity.
class Post(BaseModel):
    id: Optional[str] = None
    title: str
    content: str
    author_uid: str
    author: Optional[str] = None
    type: str # This should match PostData's post_type field
    timestamp: Optional[str] = None
    file_url: Optional[str] = None
    tags: Optional[List[str]] = []

class Comment(BaseModel):
    id: Optional[str] = None
    post_id: str
    author_id: str
    content: str
    created_at: Optional[str] = None
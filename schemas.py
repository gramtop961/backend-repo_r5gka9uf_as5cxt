"""
Database Schemas for Agricompass

Each Pydantic model represents a collection in MongoDB.
Collection name is the lowercase of the class name.

Example: class User -> collection "user"
"""
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, EmailStr

# Core users
class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: EmailStr = Field(..., description="Email address")
    password_hash: str = Field(..., description="Password hash (server-side)")
    role: Literal["farmer", "buyer", "officer", "admin"] = Field("farmer", description="User role")
    phone: Optional[str] = Field(None, description="Phone number")
    region: Optional[str] = Field(None, description="Region/Location")
    verified: bool = Field(False, description="Whether profile is verified by officer/admin")
    token: Optional[str] = Field(None, description="Simple auth token for demo sessions")

# Produce listings posted by farmers
class Listing(BaseModel):
    farmer_id: str = Field(..., description="Owner user _id as string")
    title: str = Field(..., description="Produce name, e.g., Maize")
    category: Literal["grains", "vegetables", "fruits", "legumes", "roots", "other"] = Field("other")
    description: Optional[str] = Field(None)
    unit: Literal["kg", "ton", "bag", "crate", "unit"] = Field("kg")
    quantity_available: float = Field(..., ge=0)
    unit_price: float = Field(..., ge=0)
    region: Optional[str] = Field(None)
    quality_grade: Optional[Literal["A", "B", "C"]] = None
    status: Literal["active", "inactive", "sold"] = Field("active")

# Orders placed by buyers
class OrderItem(BaseModel):
    listing_id: str
    quantity: float = Field(..., gt=0)
    unit_price: float = Field(..., ge=0)
    title: str

class Order(BaseModel):
    buyer_id: str
    items: List[OrderItem]
    total_amount: float = Field(..., ge=0)
    status: Literal["pending", "confirmed", "cancelled", "completed"] = Field("pending")
    delivery_terms: Optional[str] = None
    payment_method: Optional[str] = None

# Field officer reports
class FieldReport(BaseModel):
    officer_id: str
    farmer_id: str
    listing_id: Optional[str] = None
    notes: str
    quality_grade: Optional[Literal["A", "B", "C"]] = None
    harvest_ready: Optional[bool] = None

# Simple message entity (for future chat/communication)
class Message(BaseModel):
    sender_id: str
    recipient_id: str
    body: str
    related_order_id: Optional[str] = None


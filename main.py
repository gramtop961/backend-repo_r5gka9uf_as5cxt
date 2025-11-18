import os
import hashlib
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import User as UserSchema, Listing as ListingSchema, Order as OrderSchema, FieldReport as FieldReportSchema, Message as MessageSchema

app = FastAPI(title="Agricompass API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------
# Helpers
# ----------------------

def oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id format")

def serialize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc
    d = doc.copy()
    if "_id" in d:
        d["id"] = str(d.pop("_id"))
    # Convert nested ObjectIds in common fields
    for k in ["farmer_id", "buyer_id", "listing_id", "officer_id", "farmer", "buyer", "listing"]:
        if k in d and isinstance(d[k], ObjectId):
            d[k] = str(d[k])
    return d

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

# ----------------------
# Auth dependency
# ----------------------
class AuthedUser(BaseModel):
    id: str
    role: str
    name: Optional[str] = None

async def get_current_user(authorization: Optional[str] = Header(None)) -> AuthedUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.split(" ", 1)[1].strip()
    user = db["user"].find_one({"token": token})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = serialize_doc(user)
    return AuthedUser(id=user["id"], role=user.get("role", "farmer"), name=user.get("name"))

# ----------------------
# Schema endpoint for tooling
# ----------------------
@app.get("/schema")
def get_schema():
    # Return model field info for tooling
    def model_fields(model: BaseModel) -> Dict[str, Any]:
        return {name: str(field.annotation) for name, field in model.model_fields.items()}

    return {
        "user": model_fields(UserSchema),
        "listing": model_fields(ListingSchema),
        "order": model_fields(OrderSchema),
        "fieldreport": model_fields(FieldReportSchema),
        "message": model_fields(MessageSchema),
    }

# ----------------------
# Health & test
# ----------------------
@app.get("/")
def read_root():
    return {"message": "Agricompass API running"}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Connected & Working"
            response["connection_status"] = "Connected"
            response["collections"] = db.list_collection_names()[:10]
    except Exception as e:
        response["database"] = f"⚠️ Connected but error: {str(e)[:80]}"
    return response

# ----------------------
# Auth routes
# ----------------------
class SignUpBody(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str = Field("farmer", pattern="^(farmer|buyer|officer|admin)$")
    phone: Optional[str] = None
    region: Optional[str] = None

@app.post("/auth/signup")
def signup(body: SignUpBody):
    existing = db["user"].find_one({"email": body.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    token = hashlib.sha256(f"{body.email}:{body.role}".encode()).hexdigest()
    user = UserSchema(
        name=body.name,
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role, phone=body.phone, region=body.region,
        verified=False, token=token
    )
    user_id = create_document("user", user)
    return {"id": user_id, "token": token, "role": body.role, "name": body.name}

class LoginBody(BaseModel):
    email: EmailStr
    password: str

@app.post("/auth/login")
def login(body: LoginBody):
    user = db["user"].find_one({"email": body.email})
    if not user or user.get("password_hash") != hash_password(body.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.get("token"):
        token = hashlib.sha256(f"{user['email']}:{user.get('role','farmer')}".encode()).hexdigest()
        db["user"].update_one({"_id": user["_id"]}, {"$set": {"token": token}})
        user["token"] = token
    s = serialize_doc(user)
    return {"id": s["id"], "token": s["token"], "role": s.get("role", "farmer"), "name": s.get("name")}

@app.get("/me")
def me(current: AuthedUser = Depends(get_current_user)):
    return current.model_dump()

# ----------------------
# Listings
# ----------------------
class CreateListingBody(BaseModel):
    title: str
    category: Optional[str] = "other"
    description: Optional[str] = None
    unit: Optional[str] = "kg"
    quantity_available: float
    unit_price: float
    region: Optional[str] = None
    quality_grade: Optional[str] = None

@app.post("/listings")
def create_listing(body: CreateListingBody, current: AuthedUser = Depends(get_current_user)):
    if current.role not in ("farmer", "admin"):
        raise HTTPException(status_code=403, detail="Only farmers can create listings")
    listing = ListingSchema(
        farmer_id=current.id,
        title=body.title,
        category=body.category or "other",
        description=body.description,
        unit=body.unit or "kg",
        quantity_available=body.quantity_available,
        unit_price=body.unit_price,
        region=body.region,
        quality_grade=body.quality_grade,
        status="active",
    )
    listing_id = create_document("listing", listing)
    return {"id": listing_id}

@app.get("/listings")
def get_listings(
    category: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    min_price: Optional[float] = Query(None, ge=0),
    max_price: Optional[float] = Query(None, ge=0),
    limit: int = Query(50, ge=1, le=200)
):
    filt: Dict[str, Any] = {"status": "active"}
    if category:
        filt["category"] = category
    if region:
        filt["region"] = region
    if min_price is not None or max_price is not None:
        price_filter: Dict[str, Any] = {}
        if min_price is not None:
            price_filter["$gte"] = min_price
        if max_price is not None:
            price_filter["$lte"] = max_price
        filt["unit_price"] = price_filter
    if q:
        filt["title"] = {"$regex": q, "$options": "i"}
    docs = db["listing"].find(filt).limit(limit).sort("created_at", -1)
    return [serialize_doc(d) for d in docs]

# ----------------------
# Orders
# ----------------------
class OrderItemIn(BaseModel):
    listing_id: str
    quantity: float

class CreateOrderBody(BaseModel):
    items: List[OrderItemIn]
    delivery_terms: Optional[str] = None
    payment_method: Optional[str] = None

@app.post("/orders")
def create_order(body: CreateOrderBody, current: AuthedUser = Depends(get_current_user)):
    if current.role not in ("buyer", "admin"):
        raise HTTPException(status_code=403, detail="Only buyers can place orders")
    if not body.items:
        raise HTTPException(status_code=400, detail="No items provided")
    # Fetch listings and compute totals
    items_out = []
    total = 0.0
    for it in body.items:
        ldoc = db["listing"].find_one({"_id": oid(it.listing_id)})
        if not ldoc:
            raise HTTPException(status_code=404, detail=f"Listing not found: {it.listing_id}")
        if ldoc.get("status") != "active":
            raise HTTPException(status_code=400, detail=f"Listing not active: {it.listing_id}")
        if it.quantity <= 0:
            raise HTTPException(status_code=400, detail="Quantity must be > 0")
        unit_price = float(ldoc.get("unit_price", 0))
        items_out.append({
            "listing_id": it.listing_id,
            "quantity": it.quantity,
            "unit_price": unit_price,
            "title": ldoc.get("title", "Produce"),
        })
        total += unit_price * it.quantity
    order = OrderSchema(
        buyer_id=current.id,
        items=items_out,  # type: ignore
        total_amount=round(total, 2),
        status="pending",
        delivery_terms=body.delivery_terms,
        payment_method=body.payment_method,
    )
    order_id = create_document("order", order)
    return {"id": order_id, "total": round(total, 2), "status": "pending"}

@app.get("/orders")
def my_orders(current: AuthedUser = Depends(get_current_user)):
    if current.role not in ("buyer", "admin"):
        raise HTTPException(status_code=403, detail="Only buyers can view their orders")
    docs = db["order"].find({"buyer_id": current.id}).sort("created_at", -1)
    return [serialize_doc(d) for d in docs]

# ----------------------
# Admin/Officer basics (lightweight)
# ----------------------
class VerifyListingBody(BaseModel):
    status: str = Field(..., pattern="^(active|inactive|sold)$")

@app.patch("/listings/{listing_id}/status")
def update_listing_status(listing_id: str, body: VerifyListingBody, current: AuthedUser = Depends(get_current_user)):
    if current.role not in ("officer", "admin"):
        raise HTTPException(status_code=403, detail="Only officers/admin can update status")
    res = db["listing"].update_one({"_id": oid(listing_id)}, {"$set": {"status": body.status}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Listing not found")
    return {"id": listing_id, "status": body.status}

# ----------------------
# Simple messages (placeholder for chat)
# ----------------------
class MessageBody(BaseModel):
    recipient_id: str
    body: str
    related_order_id: Optional[str] = None

@app.post("/messages")
def send_message(body: MessageBody, current: AuthedUser = Depends(get_current_user)):
    msg = MessageSchema(
        sender_id=current.id,
        recipient_id=body.recipient_id,
        body=body.body,
        related_order_id=body.related_order_id,
    )
    msg_id = create_document("message", msg)
    return {"id": msg_id}

@app.get("/messages")
def inbox(current: AuthedUser = Depends(get_current_user)):
    docs = db["message"].find({"recipient_id": current.id}).sort("created_at", -1)
    return [serialize_doc(d) for d in docs]

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

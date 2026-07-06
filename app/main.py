from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.exceptions import BrokerAPIException, global_exception_handler, broker_exception_handler
from app.api.routes import health, shannon, valuation, fundamentals, bagger

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to frontend domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Exception Handlers
app.add_exception_handler(Exception, global_exception_handler)
app.add_exception_handler(BrokerAPIException, broker_exception_handler)

# Include Routers
app.include_router(health.router, prefix=f"{settings.API_V1_STR}", tags=["health"])
app.include_router(shannon.router, prefix=f"{settings.API_V1_STR}/shannon", tags=["shannon"])
app.include_router(valuation.router, prefix=f"{settings.API_V1_STR}/valuation", tags=["valuation"])
app.include_router(fundamentals.router, prefix=f"{settings.API_V1_STR}/fundamentals", tags=["fundamentals"])
app.include_router(bagger.router, prefix=f"{settings.API_V1_STR}/bagger", tags=["100-bagger"])

@app.get("/")
def root():
    return {"message": "Welcome to Trade Services API"}

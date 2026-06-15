import asyncio
import sys
from pathlib import Path

# Add backend directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.security import create_access_token, create_refresh_token
from app.db.session import AsyncSessionLocal
from app.db.repositories.user_repo import UserRepository
from app.db.models import UserRole

async def main():
    async with AsyncSessionLocal() as db:
        repo = UserRepository(db)
        
        # Try to find an admin user
        email = "admin@suppliermind.com"
        user = await repo.get_by_email(email)
        
        if not user:
            # Create a mock admin user for testing
            user = await repo.create_oauth_user(
                email=email,
                name="Admin User",
                provider="dev",
                oauth_id="dev-admin-123"
            )
            # Make sure they are admin
            user.role = UserRole.admin
            await db.commit()
            print("Created new dev admin user.")
        
        token = create_access_token(
            subject=str(user.id),
            role=user.role.value,
            email=user.email
        )
        refresh = create_refresh_token(subject=str(user.id))
        
        login_url = (
            f"http://localhost:5173/auth/callback"
            f"?access_token={token}"
            f"&refresh_token={refresh}"
            f"&role={user.role.value}"
        )
        
        print("\n" + "="*80)
        print("COPY & PASTE THIS URL INTO YOUR BROWSER TO LOG IN IMMEDIATELY:")
        print("="*80)
        print(login_url)
        print("="*80)
        
        print("\n" + "="*80)
        print("YOUR POSTMAN BEARER TOKEN:")
        print("="*80)
        print(token)
        print("="*80 + "\n")

if __name__ == "__main__":
    asyncio.run(main())

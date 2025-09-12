from sqlalchemy.orm import Session
import security
import models.user as user_model
import models.account as account_model
import schemas.user as user_schemas


def get_user_by_email(db: Session, email: str) -> user_model.User | None:
    """Fetches a user by their email address."""
    return db.query(user_model.User).filter(user_model.User.email == email).first()

def create_user(db: Session, user: user_schemas.UserCreate) -> user_model.User:
    """Creates a new user and a corresponding account."""
    # First, check if a user with this email already exists
    db_user = get_user_by_email(db, email=user.email)
    if db_user:
        raise ValueError("Email already registered")

    # Create a new Account for the user
    new_account = account_model.Account(name=user.law_firm_name)
    db.add(new_account)
    db.flush() # Flush to get the new_account.id before committing

    # Hash the password
    hashed_password = security.get_password_hash(user.password)
    
    # Create the new User
    db_user = user_model.User(
        email=user.email,
        hashed_password=hashed_password,
        account_id=new_account.id # <--- The link is made here
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user
# Database Migration Guide (Alembic)

This project uses **Alembic** for database schema versioning and migrations.

## Setup

Alembic is already configured and initialized. The configuration files are:
- `alembic.ini` - Configuration file
- `alembic/env.py` - Migration environment setup
- `alembic/versions/` - Migration scripts directory
- `models/base.py` - SQLAlchemy ORM models

## Current Schema

The database has 4 main tables:

### 1. **users**
- `user_id` (String, PK)
- `name` (String, NOT NULL)
- `email` (String, UNIQUE, INDEXED)
- `password_hash` (String, NOT NULL)
- `created_at` (DateTime)
- `updated_at` (DateTime)
- `is_active` (Boolean)

### 2. **refresh_tokens**
- `jti` (String, PK)
- `user_id` (String, FK → users.user_id)
- `token_hash` (String, NOT NULL)
- `expires_at` (DateTime, NOT NULL)
- `revoked` (Boolean)
- `created_at` (DateTime)

### 3. **sessions**
- `session_id` (String, PK)
- `user_id` (String, FK → users.user_id)
- `created_at` (DateTime)
- `updated_at` (DateTime)
- `title` (String)
- `lang` (String) - CHECK: supports en, hi, ta, te, mr, gu, kn, ml, pa, bn
- `is_active` (Boolean)

### 4. **messages**
- `message_id` (String, PK)
- `session_id` (String, FK → sessions.session_id)
- `role` (String) - CHECK: 'user' or 'assistant'
- `content_type` (String) - CHECK: 'text' or 'voice'
- `original_text` (Text)
- `english_text` (Text)
- `response_text` (Text)
- `detected_lang` (String)
- `audio_s3_uri` (String)
- `has_audio_out` (Boolean)
- `created_at` (DateTime)

## Common Alembic Commands

### 1. Create a New Migration (Auto-generate)
```bash
alembic revision --autogenerate -m "Description of changes"
```
This will detect changes in `models/base.py` and create a migration file.

### 2. Create a Manual Migration
```bash
alembic revision -m "Description of changes"
```
This creates an empty migration that you can edit manually.

### 3. Apply Migrations (Upgrade)
```bash
# Apply all pending migrations
alembic upgrade head

# Apply migrations up to a specific revision
alembic upgrade <revision_id>

# Apply next 1 migration
alembic upgrade +1
```

### 4. Rollback Migrations (Downgrade)
```bash
# Rollback all migrations
alembic downgrade base

# Rollback to a specific revision
alembic downgrade <revision_id>

# Rollback last 1 migration
alembic downgrade -1
```

### 5. Check Migration History
```bash
# Show current database version
alembic current

# Show migration history
alembic history --verbose
```

### 6. View Migration Details
```bash
alembic branches
alembic heads
```

## Workflow for Schema Changes

### Step 1: Update the SQLAlchemy Model
Edit `models/base.py` to add/modify columns or tables.

Example: Add a new column to users table:
```python
class User(Base):
    __tablename__ = "users"
    
    # ... existing columns ...
    phone = Column(String(20))  # New column
```

### Step 2: Generate Migration
```bash
alembic revision --autogenerate -m "Add phone column to users"
```

### Step 3: Review Migration File
Check `alembic/versions/<revision>_*.py` to ensure changes are correct.

### Step 4: Apply Migration
```bash
alembic upgrade head
```

### Step 5: Update Application Code
Update any application code that uses the new columns.

## Migration Files

All migration files are in `alembic/versions/` directory.

Current migrations:
- `f75bf60b5200_create_initial_schema_with_users_.py` - Initial schema with all 4 tables

Each migration file has:
- `upgrade()` - DDL statements to apply changes
- `downgrade()` - DDL statements to revert changes
- `revision`, `down_revision` - Migration chain metadata

## Tips

1. **Always review auto-generated migrations** - Check the SQL before running.
2. **Use descriptive migration messages** - Makes history clear and searchable.
3. **Test rollbacks** - Ensure downgrade() works before committing.
4. **Database file**: `bharatbot.db` - SQLite database file
5. **Version tracking**: Stored in `alembic_version` table

## Troubleshooting

### Migration won't apply
- Check `alembic history --verbose` to see current state
- Run `alembic current` to see what version DB is at
- Check error messages in migration file

### Need to squash migrations
```bash
alembic merge <revision1> <revision2> -m "Squash migrations"
```

### Reset database
```bash
# Remove database file
rm bharatbot.db

# Recreate from scratch
alembic upgrade head
```

## Integration with Application

The application initializes the database in `services/db.py`:

```python
from services.db import init_db

# Call on startup
init_db()
```

For Alembic migrations, this is optional since migrations are tracked separately. However, both approaches should be coordinated.

## References

- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)

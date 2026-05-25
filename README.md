# EduNexus — Smart School Management System

## Features
- **5 roles**: Superadmin, Limited Admin, Teacher, Student, Parent
- **Superadmin**: Full access — create AND delete everything; manage limited admins
- **Limited Admin**: Configurable permissions — create only, cannot delete
- **Teacher**: Sees only their assigned students/streams; posts & grades assignments
- **Student**: Sees only their own data, results, attendance; submits assignments
- **Parent**: Sees only their children's info, attendance, assignments

## Quick Start (Local)
```bash
pip install -r requirements.txt
python app.py
# → http://localhost:5000
```

## Deploy Free on Render.com (Recommended)

### Step 1 — Push to GitHub
1. Create a new repo on GitHub
2. Push this folder:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/YOUR_USERNAME/edunexus.git
   git push -u origin main
   ```

### Step 2 — Deploy on Render
1. Go to [render.com](https://render.com) → sign up free (no card needed)
2. Click **New → Web Service**
3. Connect your GitHub repo
4. Render auto-detects `render.yaml` — just confirm settings:
   - **Build command**: `pip install -r requirements.txt`
   - **Start command**: `gunicorn app:app`
5. Under **Environment Variables**, add:
   - `GROQ_API_KEY` = your key
6. Click **Deploy**

> The `render.yaml` file sets up a **1GB persistent disk** for the database so your data survives redeploys.

### Your live URL will be: `https://edunexus.onrender.com`

---

## Demo Logins (auto-created on first run)
| Role         | Username      | Password    |
|-------------|---------------|-------------|
| Superadmin  | superadmin    | super123    |
| Admin       | admin         | admin123    |
| Teacher     | teacher1      | teacher123  |
| Student     | adm20241000   | student123  |
| Parent      | parent1       | parent123   |

## Role Capabilities
| Feature           | Superadmin | Admin (limited) | Teacher | Student | Parent |
|-------------------|:----------:|:---------------:|:-------:|:-------:|:------:|
| Delete records    | ✅         | ❌              | ❌      | ❌      | ❌     |
| Manage admins     | ✅         | ❌              | ❌      | ❌      | ❌     |
| School settings   | ✅         | ❌              | ❌      | ❌      | ❌     |
| All students      | ✅         | ✅*             | Own only| Self    | Children|
| Post assignments  | ✅         | ✅*             | ✅      | ❌      | ❌     |
| Submit assignments| ❌         | ❌              | ❌      | ✅      | ❌     |
| Grade assignments | ✅         | ✅*             | Own only| ❌      | ❌     |
| Enter results     | ✅         | ✅*             | ✅      | ❌      | ❌     |
| Take attendance   | ✅         | ✅*             | ✅      | ❌      | ❌     |

*Subject to granted permissions

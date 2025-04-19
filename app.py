from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Review, Installment  # Import db, User, Review, and Installment from models.py
import os
from datetime import datetime  # Correctly import datetime

app = Flask(__name__)

# Configuration for the Flask app
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///exchangify.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24))  # Generate secure random key

# Initialize the database with the Flask app
db.init_app(app)

# Function to check if the user is an admin
def requires_admin(f):
    from functools import wraps
    
    @wraps(f)  # This preserves the original function name and metadata
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for('login'))
        user = User.query.get(session["user_id"])
        if not user or user.role != 'admin':
            flash("Access denied. Admins only.", "danger")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Function to check if the user is logged in
def requires_login(f):
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route("/reviews")
@requires_admin
def reviews():
    # Get search query if any
    search_query = request.args.get('search', '')
    
    # Fetch reviews based on search query
    if search_query:
        reviews = Review.query.filter(
            (Review.title.contains(search_query)) | 
            (Review.content.contains(search_query)) |
            (Review.tags.contains(search_query))
        ).all()
    else:
        reviews = Review.query.all()
        
    return render_template("reviews_for_admin.html", reviews=reviews, search_query=search_query)

@app.route("/users")
@requires_admin
def users():
    # Get search query if any
    search_query = request.args.get('search', '')
    
    # Fetch users based on search query
    if search_query and search_query.isdigit():
        users = User.query.filter_by(id=int(search_query)).all()
    else:
        users = User.query.all()
        
    return render_template("users_for_admin.html", users=users, search_query=search_query)

@app.route("/delete_user/<int:user_id>", methods=["POST"])
@requires_admin
def delete_user(user_id):
    # Prevent deleting the admin user
    if user_id == session.get("user_id"):
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for('users'))
    
    user = User.query.get_or_404(user_id)
    
    # Delete all reviews by this user
    Review.query.filter_by(user_id=user_id).delete()
    
    # Delete the user
    db.session.delete(user)
    db.session.commit()
    
    flash("User and all their reviews deleted successfully!", "success")
    return redirect(url_for('users'))

# Add a new route to delete reviews
@app.route("/delete_review/<int:review_id>", methods=["POST"])
@requires_admin
def delete_review(review_id):
    review = Review.query.get_or_404(review_id)
    db.session.delete(review)
    db.session.commit()
    flash("Review deleted successfully!", "success")
    return redirect(url_for('reviews'))

# Installment application routes
@app.route("/apply_installment", methods=["GET", "POST"])
@requires_login
def apply_installment():
    if request.method == "POST":
        # Get form data
        amount = request.form.get("amount")
        purpose = request.form.get("purpose")
        duration = request.form.get("duration")
        income = request.form.get("income")
        employment_status = request.form.get("employment_status")
        employer = request.form.get("employer")
        
        # Validate inputs
        if not amount or not purpose or not duration or not income or not employment_status:
            flash("All required fields must be filled!", "danger")
            return redirect(url_for('apply_installment'))
        
        try:
            amount = float(amount)
            duration = int(duration)
            income = float(income)
        except ValueError:
            flash("Invalid amount, duration, or income value", "danger")
            return redirect(url_for('apply_installment'))
        
        # Create new installment application
        new_installment = Installment(
            user_id=session["user_id"],
            amount=amount,
            purpose=purpose,
            duration=duration,
            income=income,
            employment_status=employment_status,
            employer=employer,
            status="pending"
        )
        
        # Add to database
        db.session.add(new_installment)
        db.session.commit()
        
        flash("Installment application submitted successfully!", "success")
        return redirect(url_for('user_dashboard'))
    
    return render_template("apply_installment.html")

@app.route("/installments")
@requires_admin
def installments():
    # Get search query if any
    search_query = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    
    # Base query
    query = Installment.query.join(User)
    
    # Apply filters
    if search_query:
        if search_query.isdigit():
            query = query.filter(
                (Installment.id == int(search_query)) | 
                (User.id == int(search_query))
            )
        else:
            query = query.filter(
                (User.first_name.contains(search_query)) | 
                (User.last_name.contains(search_query)) |
                (User.email.contains(search_query))
            )
    
    if status_filter:
        query = query.filter(Installment.status == status_filter)
    
    # Order by most recent first
    installments = query.order_by(Installment.created_at.desc()).all()
    
    return render_template(
        "installments_for_admin.html", 
        installments=installments, 
        search_query=search_query,
        status_filter=status_filter
    )

@app.route("/installment/<int:installment_id>")
@requires_admin
def view_installment(installment_id):
    installment = Installment.query.get_or_404(installment_id)
    return render_template("view_installment.html", installment=installment)

@app.route("/update_installment_status/<int:installment_id>", methods=["POST"])
@requires_admin
def update_installment_status(installment_id):
    installment = Installment.query.get_or_404(installment_id)
    
    status = request.form.get("status")
    admin_notes = request.form.get("admin_notes")
    
    if status not in ["approved", "rejected"]:
        flash("Invalid status", "danger")
        return redirect(url_for('installments'))
    
    installment.status = status
    installment.admin_notes = admin_notes
    installment.updated_at = datetime.utcnow()
    
    db.session.commit()
    
    flash(f"Installment application {status}", "success")
    return redirect(url_for('installments'))

@app.route("/my_installments")
@requires_login
def my_installments():
    user_id = session["user_id"]
    installments = Installment.query.filter_by(user_id=user_id).order_by(Installment.created_at.desc()).all()
    return render_template("my_installments.html", installments=installments)

# Ensure the admin user exists (run this once)
with app.app_context():
    db.create_all()  # Create database tables (if they don't exist)
    admin = User.query.filter_by(email="admin@example.com").first()
    if not admin:
        admin = User(
            email="admin@example.com",
            password=generate_password_hash("adminpassword"),
            role="admin"
        )
        db.session.add(admin)
        db.session.commit()

# Routes
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email").strip()
        password = request.form.get("password")
        role = request.form.get("role")
        
        if not email or not password or not role:
            flash("All fields are required", "danger")
            return redirect(url_for('login'))
        
        # Check if user exists with the given email
        user = User.query.filter_by(email=email).first()
        
        if not user:
            flash("Invalid email or password", "danger")
            return redirect(url_for('login'))
        
        # Verify password
        if not check_password_hash(user.password, password):
            flash("Invalid email or password", "danger")
            return redirect(url_for('login'))
        
        # Check if role matches
        if user.role != role:
            flash(f"This account is not registered as a {role}", "danger")
            return redirect(url_for('login'))
        
        # Set user session
        session["user_id"] = user.id
        
        # Redirect based on role
        if role == "admin":
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('user_dashboard'))
            
    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        # Get form data
        email = request.form.get("email").strip()
        password = request.form.get("password")
        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        mobile = request.form.get("mobile")
        gender = request.form.get("gender")
        address = request.form.get("address")
        
        # Check if the email already exists
        if User.query.filter_by(email=email).first():
            flash("Email already in use. Please try another one.", "danger")
            return redirect(url_for('signup'))
        
        # Create new user
        hashed_password = generate_password_hash(password)
        user = User(
            email=email, 
            password=hashed_password, 
            role="user",
            first_name=first_name,
            last_name=last_name,
            mobile=mobile,
            gender=gender,
            address=address
        )
        
        # Save to database
        db.session.add(user)
        db.session.commit()

        # Log the user in after sign-up (automatically set session)
        session["user_id"] = user.id  # Store user ID in the session

        flash("Sign up successful! Welcome!", "success")
        return redirect(url_for('user_dashboard'))  # Redirect to the user dashboard after sign-up
    
    # Add this return statement for GET requests
    return render_template("signup.html")

@app.route("/admin_dashboard")
@requires_admin
def admin_dashboard():
    # Get user count for the dashboard
    user_count = User.query.filter_by(role='user').count()
    # Get recent reviews for the dashboard
    reviews = Review.query.order_by(Review.date.desc()).limit(5).all()
    # Get pending installment applications
    pending_installments = Installment.query.filter_by(status="pending").count()
    
    return render_template(
        "admin_dashboard.html", 
        user_count=user_count, 
        reviews=reviews,
        pending_installments=pending_installments
    )

@app.route("/user_dashboard")
@requires_login
def user_dashboard():
    user = User.query.get(session["user_id"])  # Fetch user from the database using the session ID
    
    # Get user's installment applications
    installments = Installment.query.filter_by(user_id=user.id).order_by(Installment.created_at.desc()).limit(3).all()
    
    return render_template("user_dashboard.html", user=user, installments=installments)

@app.route("/profile/<int:user_id>")
def user_profile(user_id):
    user = User.query.get_or_404(user_id)
    return render_template("user_profile.html", user=user)

@app.route("/edit_profile/<int:user_id>", methods=["GET", "POST"])
def edit_profile(user_id):
    user = User.query.get_or_404(user_id)

    if request.method == "POST":
        user.first_name = request.form["first_name"]
        user.last_name = request.form["last_name"]
        user.email = request.form["email"]
        user.mobile = request.form["mobile"]
        user.gender = request.form["gender"]
        user.password = generate_password_hash(request.form["password"])  # Update password securely
        user.address = request.form["address"]

        db.session.commit()  # Save the updated profile to the database
        flash("Profile updated successfully", "success")
        return redirect(url_for('edit_success'))  # Redirect to the success page after update

    return render_template("edit_profile.html", user=user)

@app.route("/edit_success")
def edit_success():
    return render_template("edit_success.html")

@app.route("/add_review", methods=["GET", "POST"])
def add_review():
    if "user_id" not in session:
        flash("You need to log in to submit a review.", "warning")
        return redirect(url_for('login'))

    if request.method == "POST":
        title = request.form.get("title").strip()
        content = request.form.get("content").strip()
        tags = request.form.get("tags")
        date = request.form.get("date")

        # Validate inputs
        if not title or not content or not tags or not date:
            flash("All fields are required!", "danger")
            return redirect(url_for('add_review'))

        try:
            date_obj = datetime.strptime(date, "%Y-%m-%d")  # Convert string to datetime object
        except ValueError:
            flash("Invalid date format", "danger")
            return redirect(url_for('add_review'))

        # Create new review
        new_review = Review(
            title=title,
            content=content,
            tags=tags,
            date=date_obj,
            user_id=session["user_id"]
        )

        # Add the review to the database
        db.session.add(new_review)
        db.session.commit()

        flash("Review added successfully!", "success")
        return redirect(url_for('user_dashboard'))  # Redirect back to the dashboard after success

    return render_template("add_review_for_user.html")  # Ensure you return the template if it's a GET request

@app.route("/logout")
def logout():
    session.clear()  # Clear all session data
    flash("You have successfully logged out.", "info")  # Notify user they logged out
    return redirect(url_for('login'))  # Redirect to login page after logging out

if __name__ == "__main__":
    app.run(debug=True)

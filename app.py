from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///users.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = os.urandom(24)  # Secret key for session management

# Configure upload folder for donation images
UPLOAD_FOLDER = 'static/uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

db = SQLAlchemy(app)

################chat 

# Chat Message Model
class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_messages')
    receiver = db.relationship('User', foreign_keys=[receiver_id], backref='received_messages')

from datetime import datetime
from flask import jsonify

@app.route("/chat")
def chat():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    users = User.query.filter(User.id != session['user_id']).all()
    return render_template("chat.html", users=users)

@app.route("/api/users/search", methods=["GET"])
def search_users():
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
        
    query = request.args.get("q", "")
    users = User.query.filter(
        (User.id != session['user_id']) & 
        ((User.first_name.like(f"%{query}%")) | 
        (User.last_name.like(f"%{query}%")))
    ).all()
    
    return jsonify([{
        "id": user.id,
        "name": f"{user.first_name} {user.last_name}",
    } for user in users])

@app.route("/api/messages/<int:user_id>", methods=["GET"])
def get_messages(user_id):
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
        
    current_user_id = session['user_id']
    
    messages = ChatMessage.query.filter(
        ((ChatMessage.sender_id == current_user_id) & (ChatMessage.receiver_id == user_id)) |
        ((ChatMessage.sender_id == user_id) & (ChatMessage.receiver_id == current_user_id))
    ).order_by(ChatMessage.timestamp).all()
    
    return jsonify([{
        "id": msg.id,
        "senderId": msg.sender_id,
        "text": msg.message,
        "timestamp": msg.timestamp.isoformat()
    } for msg in messages])

@app.route("/api/messages/send", methods=["POST"])
def send_message():
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
        
    current_user_id = session['user_id']
    
    data = request.json
    receiver_id = data.get("receiverId")
    message_text = data.get("message")
    
    if not receiver_id or not message_text:
        return jsonify({"error": "Missing required fields"}), 400
    
    message = ChatMessage(
        sender_id=current_user_id,
        receiver_id=receiver_id,
        message=message_text
    )
    
    db.session.add(message)
    db.session.commit()
    
    return jsonify({
        "id": message.id,
        "senderId": message.sender_id,
        "text": message.message,
        "timestamp": message.timestamp.isoformat()
    })

################### Donations ###################

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Donation Model
class Donation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    donor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Can be null for admin donations
    item_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    condition = db.Column(db.String(50), nullable=False)
    image_filename = db.Column(db.String(255), nullable=True)  # Store the image filename
    status = db.Column(db.String(20), default="pending")  # pending, accepted, declined, completed
    is_admin_donation = db.Column(db.Boolean, default=False)  # Flag for admin donations
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    donor = db.relationship('User', foreign_keys=[donor_id], backref='donations_made')
    recipient = db.relationship('User', foreign_keys=[recipient_id], backref='donations_received')

@app.route("/donations")
def donations():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Get donations made by the user
    donations_made = Donation.query.filter_by(donor_id=session['user_id']).all()
    
    # Get donations received by the user
    donations_received = Donation.query.filter_by(recipient_id=session['user_id']).all()
    
    # Get admin donations if the current user is an admin
    current_user = User.query.get(session['user_id'])
    admin_donations = []
    if current_user.is_admin:
        admin_donations = Donation.query.filter_by(is_admin_donation=True).all()
    
    return render_template("donations.html", 
                          donations_made=donations_made, 
                          donations_received=donations_received,
                          admin_donations=admin_donations,
                          is_admin=current_user.is_admin)

@app.route("/donations/new", methods=["GET", "POST"])
def new_donation():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == "POST":
        recipient_type = request.form.get("recipient_type")
        recipient_id = None
        is_admin_donation = False
        
        if recipient_type == "user":
            recipient_id = request.form.get("recipient_id")
            if not recipient_id:
                flash("Please select a recipient", "danger")
                return redirect(url_for("new_donation"))
        elif recipient_type == "admin":
            is_admin_donation = True
        
        item_name = request.form.get("item_name")
        description = request.form.get("description")
        condition = request.form.get("condition")
        
        # Handle image upload
        image_filename = None
        if 'item_image' in request.files:
            file = request.files['item_image']
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                # Add timestamp to filename to make it unique
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                image_filename = f"{timestamp}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
        
        # Create new donation
        donation = Donation(
            donor_id=session['user_id'],
            recipient_id=recipient_id,
            item_name=item_name,
            description=description,
            condition=condition,
            image_filename=image_filename,
            status="pending",
            is_admin_donation=is_admin_donation
        )
        
        db.session.add(donation)
        db.session.commit()
        
        flash("Donation created successfully!", "success")
        return redirect(url_for("donations"))
    
    # Get all users except current user
    users = User.query.filter(User.id != session['user_id']).all()
    return render_template("new_donation.html", users=users)

@app.route("/donations/<int:donation_id>")
def view_donation(donation_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    donation = Donation.query.get_or_404(donation_id)
    current_user = User.query.get(session['user_id'])
    
    # Check if user is either donor, recipient, or admin (for admin donations)
    if (donation.donor_id != session['user_id'] and 
        donation.recipient_id != session['user_id'] and 
        not (current_user.is_admin and donation.is_admin_donation)):
        flash("You don't have permission to view this donation", "danger")
        return redirect(url_for("donations"))
    
    return render_template("view_donation.html", donation=donation, is_admin=current_user.is_admin)

@app.route("/donations/<int:donation_id>/update_status", methods=["POST"])
def update_donation_status(donation_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    donation = Donation.query.get_or_404(donation_id)
    current_user = User.query.get(session['user_id'])
    
    # Check if user is recipient or admin (for admin donations)
    if (donation.recipient_id != session['user_id'] and 
        not (current_user.is_admin and donation.is_admin_donation)):
        flash("You don't have permission to update this donation", "danger")
        return redirect(url_for("donations"))
    
    new_status = request.form.get("status")
    if new_status in ["accepted", "declined", "completed"]:
        donation.status = new_status
        db.session.commit()
        flash(f"Donation {new_status} successfully!", "success")
    
    return redirect(url_for("view_donation", donation_id=donation_id))

######################################

# User Model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(100), nullable=False, unique=True)
    gender = db.Column(db.String(10), nullable=False)
    address = db.Column(db.String(200), nullable=False)
    password = db.Column(db.String(200), nullable=False)
    mobile = db.Column(db.String(20), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)  # New field to identify admin users

# Create database and sample users
with app.app_context():
    db.create_all()
    # Only add sample users if the database is empty
    if not User.query.first():
        demo_user1 = User(
            first_name="Abc",
            last_name="Def",
            email="abc@gmail.com",
            gender="Male",
            address="123 Street",
            password="password123",
            mobile="1234567890"
        )
        demo_user2 = User(
            first_name="Jane",
            last_name="Doe",
            email="jane@gmail.com",
            gender="Female",
            address="456 Avenue",
            password="password456",
            mobile="9876543210"
        )
        # Create an admin user
        admin_user = User(
            first_name="Admin",
            last_name="User",
            email="admin@exchangeify.com",
            gender="Other",
            address="Admin Office",
            password="admin123",
            mobile="0000000000",
            is_admin=True
        )
        db.session.add(demo_user1)
        db.session.add(demo_user2)
        db.session.add(admin_user)
        db.session.commit()

# Authentication routes
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        
        user = User.query.filter_by(email=email).first()
        
        if user and user.password == password:
            session['user_id'] = user.id
            session['user_name'] = f"{user.first_name} {user.last_name}"
            return redirect(url_for("home"))
        else:
            return render_template("login.html", error="Invalid email or password")
    
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        email = request.form.get("email")
        gender = request.form.get("gender")
        address = request.form.get("address")
        password = request.form.get("password")
        mobile = request.form.get("mobile")
        
        # Check if email already exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            return render_template("register.html", error="Email already registered")
        
        # Create new user
        new_user = User(
            first_name=first_name,
            last_name=last_name,
            email=email,
            gender=gender,
            address=address,
            password=password,
            mobile=mobile
        )
        
        db.session.add(new_user)
        db.session.commit()
        
        # Log in the new user
        session['user_id'] = new_user.id
        session['user_name'] = f"{new_user.first_name} {new_user.last_name}"
        
        return redirect(url_for("home"))
    
    return render_template("register.html")

@app.route("/logout")
def logout():
    session.pop('user_id', None)
    session.pop('user_name', None)
    return redirect(url_for("login"))

@app.route("/")
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template("home.html", user_name=session.get('user_name'))

@app.route("/profile/21101096/<int:user_id>")
def profile(user_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Only allow users to view their own profile
    if user_id != session['user_id']:
        return redirect(url_for('profile', user_id=session['user_id']))
        
    user = User.query.get_or_404(user_id)
    return render_template("profile.html", user=user)

@app.route("/edit_profile/21101096/<int:user_id>")
def edit_profile(user_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Only allow users to edit their own profile
    if user_id != session['user_id']:
        return redirect(url_for('edit_profile', user_id=session['user_id']))
        
    user = User.query.get_or_404(user_id)
    return render_template("edit_profile.html", user=user)

@app.route("/update_profile/21101096/<int:user_id>", methods=["POST"])
def update_profile(user_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Only allow users to update their own profile
    if user_id != session['user_id']:
        return redirect(url_for('home'))
        
    user = User.query.get_or_404(user_id)
    user.first_name = request.form.get("first_name")
    user.last_name = request.form.get("last_name")
    user.email = request.form.get("email")
    user.gender = request.form.get("gender")
    user.address = request.form.get("address")
    user.password = request.form.get("password")
    user.mobile = request.form.get("mobile")
    
    # Update session name if it changed
    session['user_name'] = f"{user.first_name} {user.last_name}"
    
    db.session.commit()
    return redirect(url_for("success"))

@app.route("/success")
def success():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template("success.html")

# REST API 1: Get user profile (for frontend or external use)
@app.route("/get_profile/21101096/<int:user_id>", methods=["GET"])
def get_profile(user_id):
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
        
    # Only allow users to get their own profile
    if user_id != session['user_id']:
        return jsonify({"error": "Unauthorized"}), 403
        
    user = User.query.get(user_id)
    if user:
        return jsonify({
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "gender": user.gender,
            "address": user.address,
            "password": "*" * len(user.password),  # Show masked password
            "mobile": user.mobile
        })
    return jsonify({"error": "User not found"}), 404

# REST API 2: Update user profile (for external apps)
@app.route("/update_user_profile/21101096/<int:user_id>", methods=["POST"])
def update_user_profile(user_id):
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
        
    # Only allow users to update their own profile
    if user_id != session['user_id']:
        return jsonify({"error": "Unauthorized"}), 403
        
    user = User.query.get_or_404(user_id)
    user.first_name = request.json.get("first_name", user.first_name)
    user.last_name = request.json.get("last_name", user.last_name)
    user.email = request.json.get("email", user.email)
    user.gender = request.json.get("gender", user.gender)
    user.address = request.json.get("address", user.address)
    user.password = request.json.get("password", user.password)
    user.mobile = request.json.get("mobile", user.mobile)
    
    # Update session name if it changed
    session['user_name'] = f"{user.first_name} {user.last_name}"
    
    db.session.commit()
    return jsonify({"message": "Profile updated successfully!"}), 200

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=1096)

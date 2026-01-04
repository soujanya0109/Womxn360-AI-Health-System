import os
from flask import Flask, render_template, request, redirect, url_for, flash
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

# --- DATABASE IMPORTS ---
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user

# --- AI SETUP ---
try:
    import google.generativeai as genai

    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

app = Flask(__name__)

# --- FIX: ALLOW TEMPLATES TO DO DATE MATH ---
app.jinja_env.globals.update(timedelta=timedelta)

# --- CONFIGURATION ---
app.config['SECRET_KEY'] = 'womxn360secretkey'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///womxn360.db'
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- 🔑 PASTE YOUR API KEY BELOW ---
GOOGLE_API_KEY = "YOUR_GOOGLE_API_KEY_HERE"

# --- AI MODEL SELECTOR ---
active_model = None
if AI_AVAILABLE and "PASTE" not in GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        preferred_models = ['gemini-2.5-flash', 'gemini-1.5-flash', 'gemini-pro']
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]

        for model_name in preferred_models:
            if f"models/{model_name}" in available_models or model_name in available_models:
                active_model = genai.GenerativeModel(model_name)
                print(f"✅ AI Connected: {model_name}")
                break
        if not active_model and available_models:
            active_model = genai.GenerativeModel(available_models[0])
    except Exception as e:
        print(f"AI Error: {e}")


# --- DATABASE MODELS ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)


class MenopauseLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, default=datetime.now)
    score = db.Column(db.Integer)
    intensity = db.Column(db.Integer)


class PeriodLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    cycle_length = db.Column(db.Integer, nullable=False)


# NEW: Model to store Pregnancy Data (Persistent)
class PregnancyLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    lmp_date = db.Column(db.Date, nullable=False)  # Last Menstrual Period


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# --- HELPER FUNCTIONS ---
def get_cycle_phase(last_period_str, cycle_length):
    try:
        last_period = datetime.strptime(last_period_str, '%Y-%m-%d').date()
        today = datetime.now().date()
        days_passed = (today - last_period).days
        day_in_cycle = days_passed % cycle_length
        if 0 <= day_in_cycle <= 5:
            return "Menstrual", "Rest, keep warm.", days_passed
        elif 6 <= day_in_cycle <= 12:
            return "Follicular", "High energy!", days_passed
        elif 13 <= day_in_cycle <= 15:
            return "Ovulation", "Peak fertility.", days_passed
        else:
            return "Luteal", "PMS likely.", days_passed
    except:
        return None, None, None


def get_pregnancy_stats(lmp_obj):
    try:
        # Calculate stats based on the stored Date object
        due = lmp_obj + timedelta(days=280)
        weeks = (datetime.now().date() - lmp_obj).days // 7
        sizes = ['Poppy Seed', 'Blueberry', 'Raspberry', 'Fig', 'Avocado', 'Mango', 'Pumpkin', 'Watermelon',
                 'Pineapple']
        size_idx = min(weeks // 5, len(sizes) - 1)
        # Prevent negative weeks if date is in future
        weeks = max(0, weeks)
        return weeks, due.strftime('%B %d, %Y'), sizes[size_idx]
    except:
        return 0, "Unknown", "Unknown"


# --- ROUTES ---

@app.route('/')
def home():
    return render_template('home.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if User.query.filter_by(username=username).first():
            flash('Username already exists!')
            return redirect(url_for('register'))
        new_user = User(username=username, password=generate_password_hash(password, method='pbkdf2:sha256'))
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        return redirect(url_for('home'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('home'))
        else:
            flash('Incorrect login details')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))


# --- APP FEATURES ---

@app.route('/period', methods=['GET', 'POST'])
@login_required
def period():
    res = None
    if request.method == 'POST':
        date_str = request.form.get('last_period')
        length = int(request.form.get('cycle_length'))
        new_log = PeriodLog(
            user_id=current_user.id,
            start_date=datetime.strptime(date_str, '%Y-%m-%d').date(),
            cycle_length=length
        )
        db.session.add(new_log)
        db.session.commit()
        p, a, d = get_cycle_phase(date_str, length)
        res = {'phase': p, 'advice': a, 'day': d}

    history = PeriodLog.query.filter_by(user_id=current_user.id).order_by(PeriodLog.start_date.desc()).all()
    return render_template('period.html', result=res, history=history)


# --- UPDATED PREGNANCY ROUTE (Persistent) ---
@app.route('/pregnancy', methods=['GET', 'POST'])
@login_required
def pregnancy():
    # 1. Check if user already has data
    log = PregnancyLog.query.filter_by(user_id=current_user.id).first()
    result = None

    # 2. Handle Form Update
    if request.method == 'POST':
        date_str = request.form.get('lmp_date')
        lmp = datetime.strptime(date_str, '%Y-%m-%d').date()

        if log:
            log.lmp_date = lmp  # Update existing
        else:
            log = PregnancyLog(user_id=current_user.id, lmp_date=lmp)  # Create new
            db.session.add(log)
        db.session.commit()

    # 3. Calculate Stats to Display (from DB)
    if log:
        weeks, due_date, size = get_pregnancy_stats(log.lmp_date)
        # Calculate progress % (40 weeks total)
        progress = min(max((weeks / 40) * 100, 5), 100)
        result = {'weeks': weeks, 'due_date': due_date, 'size': size, 'progress': int(progress), 'lmp': log.lmp_date}

    return render_template('pregnancy.html', result=result)


@app.route('/postpartum')
@login_required
def postpartum():
    return render_template('postpartum.html')


@app.route('/menopause', methods=['GET', 'POST'])
@login_required
def menopause():
    result = None
    if request.method == 'POST':
        symptoms = request.form.getlist('symptoms')
        intensity = int(request.form.get('intensity', 0))
        score = len(symptoms) + (intensity // 2)
        log = MenopauseLog(user_id=current_user.id, score=score, intensity=intensity)
        db.session.add(log)
        db.session.commit()
        if score < 3:
            status, tip = "Mild", "Focus on diet."
        elif score < 7:
            status, tip = "Moderate", "Consider Magnesium."
        else:
            status, tip = "High", "Consult a specialist."
        result = {'score': score, 'status': status, 'tip': tip, 'count': len(symptoms)}

    logs = MenopauseLog.query.filter_by(user_id=current_user.id).order_by(MenopauseLog.date.asc()).limit(10).all()
    dates = [log.date.strftime('%b %d') for log in logs]
    scores = [log.intensity for log in logs]
    return render_template('menopause.html', result=result, dates=dates, scores=scores)


# --- RISK PREDICTION MODULE ---
@app.route('/risk_assessment', methods=['GET', 'POST'])
@login_required
def risk_assessment():
    result = None
    if request.method == 'POST':
        # 1. Get Health Data
        bmi = float(request.form.get('bmi', 0))
        cycle_regularity = request.form.get('cycle_regularity')  # 'regular' or 'irregular'
        weight_gain = request.form.get('weight_gain')  # 'yes' or 'no'
        hair_growth = request.form.get('hair_growth')  # 'yes' or 'no' (Hirsutism)
        acne = request.form.get('acne')  # 'yes' or 'no'

        # 2. Risk Calculation Algorithm (Rule-Based AI)
        risk_score = 0

        # BMI Logic
        if bmi > 25:
            risk_score += 20
        elif bmi > 30:
            risk_score += 30

        # Cycle Logic (Biggest Indicator)
        if cycle_regularity == 'irregular': risk_score += 40

        # Symptom Logic
        if weight_gain == 'yes': risk_score += 15
        if hair_growth == 'yes': risk_score += 15  # High testosterone indicator
        if acne == 'yes': risk_score += 10

        # Cap score at 100%
        final_score = min(risk_score, 100)

        # 3. Determine Classification
        if final_score < 30:
            level = "Low Risk"
            msg = "Your symptoms do not indicate PCOS at this time."
            color = "success"
        elif final_score < 60:
            level = "Moderate Risk"
            msg = "You have some symptoms of hormonal imbalance. Monitor your cycle closely."
            color = "warning"
        else:
            level = "High Risk"
            msg = "Your profile strongly matches PCOS markers. We recommend seeing an Endocrinologist."
            color = "danger"

        result = {'score': final_score, 'level': level, 'msg': msg, 'color': color}

    return render_template('risk.html', result=result)

@app.route('/chat', methods=['POST'])
@login_required
def chat():
    user_msg = request.json.get('message', '')
    if not active_model: return {'response': "AI Offline."}
    try:
        # Context-Aware AI
        context_str = f"User is {current_user.username}. "

        # Check Pregnancy
        preg_log = PregnancyLog.query.filter_by(user_id=current_user.id).first()
        if preg_log:
            w, _, _ = get_pregnancy_stats(preg_log.lmp_date)
            context_str += f"She is pregnant in Week {w}. "

        prompt = f"You are Eve, a health assistant. CONTEXT: {context_str}. User asks: {user_msg}"
        response = active_model.generate_content(prompt)
        return {'response': response.text}
    except Exception as e:
        return {'response': f"Error: {str(e)}"}

# --- HYGIENE & PREVENTION MODULE ---
@app.route('/hygiene')
@login_required
def hygiene():
    return render_template('hygiene.html')


# --- AI WELLNESS PLANNER MODULE ---
@app.route('/wellness', methods=['GET', 'POST'])
@login_required
def wellness():
    plan = None
    if request.method == 'POST':
        # 1. Get User Preferences
        goal = request.form.get('goal')  # e.g. "Manage PCOS"
        diet = request.form.get('diet')  # e.g. "Vegetarian"
        activity = request.form.get('activity')  # e.g. "Sedentary"

        if not active_model:
            plan = "⚠️ AI is offline. Please check your API Key."
        else:
            # 2. Construct the Prompt
            prompt = f"""
            Act as a professional nutritionist and fitness coach for women.
            Create a 1-Day Wellness Plan for a woman with the following profile:
            - Health Goal: {goal}
            - Diet Preference: {diet}
            - Activity Level: {activity}

            Please provide the output in this strict format:

            🍳 **Breakfast:** [Suggestion]
            🥗 **Lunch:** [Suggestion]
            🍲 **Dinner:** [Suggestion]
            🥨 **Snack:** [Suggestion]
            🧘‍♀️ **Recommended Movement:** [Specific exercise]
            💡 **Wellness Tip:** [One actionable tip]

            Keep it concise and encouraging.
            """

            # 3. Get Result from AI
            try:
                response = active_model.generate_content(prompt)
                plan = response.text
            except Exception as e:
                plan = f"Error generating plan: {e}"

    return render_template('wellness.html', plan=plan)


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
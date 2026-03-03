import streamlit as st
from datetime import datetime, time
import firebase_admin
from firebase_admin import credentials, firestore
import base64
import pandas as pd
from io import BytesIO
import json

# =============================
# CONFIG
# =============================
st.set_page_config(page_title="Attendance System", layout="wide")

# =============================
# FIREBASE INIT (STREAMLIT CLOUD SAFE)
# =============================

if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)

    db = firestore.client()

st.success("Firebase connected successfully!")

# =============================
# LOGIN
# =============================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.title("🔐 Login")
    username = st.text_input("Enter Username")

    if st.button("Login"):
        if username.strip() != "":
            st.session_state.logged_in = True
            st.session_state.username = username.strip()
            st.rerun()
        else:
            st.warning("Please enter username")

    st.stop()

# =============================
# SIDEBAR
# =============================
st.sidebar.title("📌 Menu")
menu = st.sidebar.radio(
    "Navigation",
    ["Attendance", "Dashboard", "Weekly Report"]
)

# =============================
# ATTENDANCE PAGE
# =============================
if menu == "Attendance":

    st.title("📋 Attendance System")

    action = st.radio("Select Action", ["Check-in", "Check-out"])

    checker = st.selectbox(
        "Select Checker",
        ["", "Checker A", "Checker B", "Checker C"]
    )

    late_reason = st.text_area("Reason for Late")
    early_reason = st.text_area("Reason for Early Leave")

    image = st.camera_input("📷 Take a photo")

    if st.button("Submit Attendance"):

        if image is None:
            st.warning("Please take a photo!")
            st.stop()

        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        current_time = now.time()

        # ===== CHẶN CHECK TRÙNG =====
        existing_docs = db.collection("attendance")\
            .where("Username", "==", st.session_state.username)\
            .where("Date", "==", today_str)\
            .where("Action", "==", action)\
            .stream()

        if list(existing_docs):
            st.error(f"You already did {action} today!")
            st.stop()

        # ===== VALIDATE GIỜ =====
        if action == "Check-in" and current_time > time(8, 15):
            if late_reason.strip() == "" or checker == "":
                st.error("Late check-in! Must fill reason and select checker.")
                st.stop()

        if action == "Check-out" and current_time < time(18, 30):
            if early_reason.strip() == "" or checker == "":
                st.error("Early checkout! Must fill reason and select checker.")
                st.stop()

        # ===== ENCODE ẢNH BASE64 =====
        image_bytes = image.getvalue()
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")

        # ===== LƯU FIRESTORE =====
        db.collection("attendance").add({
            "Username": st.session_state.username,
            "Action": action,
            "Checker": checker,
            "Time": now.strftime("%H:%M:%S"),
            "Date": today_str,
            "Late Reason": late_reason,
            "Early Leave Reason": early_reason,
            "ImageBase64": image_base64,
            "Timestamp": firestore.SERVER_TIMESTAMP
        })

        st.success(f"✅ {action} successful at {now.strftime('%H:%M:%S')}")

# =============================
# DASHBOARD PAGE
# =============================
if menu == "Dashboard":

    st.title("📊 Dashboard - Today")

    today_str = datetime.now().strftime("%Y-%m-%d")

    docs = db.collection("attendance") \
        .where("Date", "==", today_str) \
        .stream()

    records = [doc.to_dict() for doc in docs]
    records = [r for r in records if r.get("Timestamp") is not None]

    records = sorted(
        records,
        key=lambda x: x["Timestamp"],
        reverse=True
    )

    if not records:
        st.info("No records today.")
    else:
        st.metric("Total Records Today", len(records))

        for row in records:
            col1, col2 = st.columns([3, 1])

            with col1:
                st.write(f"👤 **{row['Username']}**")
                st.write(f"📝 {row['Action']}")
                st.write(f"🕒 {row['Time']}")
                if row["Checker"]:
                    st.write(f"✔ Checker: {row['Checker']}")
                if row["Late Reason"]:
                    st.write(f"⏰ Late: {row['Late Reason']}")
                if row["Early Leave Reason"]:
                    st.write(f"🏃 Early: {row['Early Leave Reason']}")

            with col2:
                image_bytes = base64.b64decode(row["ImageBase64"])
                st.image(image_bytes, width=150)

            st.divider()

# =============================
# WEEKLY REPORT PAGE
# =============================
if menu == "Weekly Report":

    st.title("📄 Weekly Attendance Report")

    start_date = st.date_input("Start Date")
    end_date = st.date_input("End Date")

    if st.button("Generate Report"):

        if start_date > end_date:
            st.error("Start date must be before end date")
            st.stop()

        docs = db.collection("attendance").stream()
        records = []

        for doc in docs:
            data = doc.to_dict()
            record_date = datetime.strptime(data["Date"], "%Y-%m-%d").date()

            if start_date <= record_date <= end_date:
                records.append(data)

        if not records:
            st.warning("No records in selected range.")
            st.stop()

        df = pd.DataFrame(records)

        # 🔥 FIX TIMEZONE ERROR
        if "Timestamp" in df.columns:
            df["Timestamp"] = pd.to_datetime(df["Timestamp"]).dt.tz_localize(None)

        summary = df.groupby("Username").agg(
            Total_Records=("Username", "count"),
            Late_Count=("Late Reason", lambda x: (x != "").sum()),
            Early_Count=("Early Leave Reason", lambda x: (x != "").sum())
        ).reset_index()

        st.subheader("📊 Summary")

        for _, row in summary.iterrows():
            username = row["Username"]
            total = row["Total_Records"]
            late = row["Late_Count"]
            early = row["Early_Count"]

            if late > 5 and early > 5:
                name_display = f"<b style='color:red'>{username}</b>"
            elif late > 5 or early > 5:
                name_display = f"<span style='color:red'>{username}</span>"
            else:
                name_display = username

            st.markdown(
                f"""
                👤 {name_display}  
                • Total: {total}  
                • Late: {late}  
                • Early: {early}  
                ---
                """,
                unsafe_allow_html=True
            )

        # ===== EXPORT EXCEL =====
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Raw Data")
            summary.to_excel(writer, index=False, sheet_name="Summary")

        st.download_button(
            label="⬇ Download Excel Report",
            data=output.getvalue(),
            file_name=f"attendance_{start_date}_to_{end_date}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
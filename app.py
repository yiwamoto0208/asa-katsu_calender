# app.py (管理者編集機能追加版)

import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import calendar
import pandas as pd
import uuid

# --- ページ設定 ---
st.set_page_config(
    page_title="見守りシフト管理カレンダー",
    page_icon="🗓️",
    layout="wide"
)

# --- Firebaseの初期化 ---
# app.pyのこの関数を、以下のコードに丸ごと置き換える
@st.cache_resource
def init_firebase():
    """Firebase Admin SDKを初期化する"""
    try:
        # secretsから「ファイルパス」ではなく「辞書」を直接読み込む
        creds_dict = st.secrets["firebase"]
        creds = credentials.Certificate(creds_dict)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(creds)
        return firestore.client()
    except Exception as e:
        st.error(f"Firebaseの初期化に失敗しました: {e}")
        st.warning("Streamlit Community CloudのSecrets設定が正しいか確認してください。")
        return None

db = init_firebase()
if not db:
    st.stop()

# --- Firestoreコレクションへの参照 ---
EVENTS_COLLECTION = "shift_calendar/data/events"
DAY_STATUS_COLLECTION = "shift_calendar/data/day_status"
MONTH_LOCKS_COLLECTION = "shift_calendar/data/month_locks"
BOARD_COLLECTION = "shift_calendar/data/bulletin_board"
MAX_SHIFTS_PER_DAY = 3

# --- セッション状態の初期化 ---
if 'current_date' not in st.session_state:
    st.session_state.current_date = datetime.now()
if 'admin_mode' not in st.session_state:
    st.session_state.admin_mode = False
if 'user_name' not in st.session_state:
    st.session_state.user_name = ""

# --- データ取得・クリーンアップ関数 ---
@st.cache_data(ttl=60)
def get_firestore_data(year, month):
    """指定された月のFirestoreデータを取得する"""
    month_id = f"{year}-{month:02d}"
    
    events_ref = db.collection(EVENTS_COLLECTION)
    query = events_ref.where('month_id', '==', month_id)
    events = {doc.id: doc.to_dict() for doc in query.stream()}
    
    day_status_ref = db.collection(DAY_STATUS_COLLECTION)
    query = day_status_ref.where('month_id', '==', month_id)
    day_status = {doc.id: doc.to_dict() for doc in query.stream()}
    
    month_lock_doc = db.collection(MONTH_LOCKS_COLLECTION).document(month_id).get()
    is_month_locked = month_lock_doc.exists and month_lock_doc.to_dict().get('isLocked', False)

    board_ref = db.collection(BOARD_COLLECTION)
    query = board_ref.where('month_id', '==', month_id).order_by('timestamp', direction=firestore.Query.DESCENDING)
    board_messages = [doc.to_dict() for doc in query.stream()]

    return events, day_status, is_month_locked, board_messages

def cleanup_old_board_messages():
    """投稿から2週間以上経過した掲示板メッセージを削除する"""
    two_weeks_ago = datetime.now() - timedelta(weeks=2)
    old_messages_query = db.collection(BOARD_COLLECTION).where('timestamp', '<', two_weeks_ago).stream()
    
    batch = db.batch()
    deleted_count = 0
    for doc in old_messages_query:
        batch.delete(doc.reference)
        deleted_count += 1
    
    if deleted_count > 0:
        batch.commit()

# --- UIコンポーネントとロジック ---

def show_welcome_and_name_input():
    """ウェルカムメッセージと名前入力フォームを表示する"""
    st.subheader("ようこそ！シフト管理を始めるには、まずお名前を教えてください。")
    st.info("💡 入力後はいつでもブラウザを閉じて終了できます。データは自動で保存されます。")
    
    with st.form("name_form"):
        name = st.text_input(
            "あなたのフルネームを入力してください", 
            placeholder="例：山田太郎",
            help="姓と名の間は詰めて入力してください。"
        )
        submitted = st.form_submit_button("利用開始")
        if submitted and name:
            st.session_state.user_name = name.replace(" ", "").replace("　", "")
            st.rerun()
        elif submitted:
            st.warning("お名前を入力してください。")

def show_main_app():
    """メインのアプリケーションUI（カレンダーや掲示板）を表示する"""
    st.success(f"**{st.session_state.user_name}** さん、こんにちは！")
    
    with st.expander("📖 かんたんな使い方", expanded=True):
        st.markdown("""
        1. **シフトに入りたい日をクリック**: カレンダーで「開催日」となっている日付の「シフトに入る」ボタンを押します。
        2. **シフトを確認**: あなたの名前がカレンダーに表示されたら登録完了です。
        3. **シフトを削除**: 間違えて登録した場合は、自分の名前の横にある「✖️」ボタンを押すと削除できます。
        """)
    
    show_calendar()
    show_board_and_info()


def show_calendar():
    """カレンダーのメインUIを描画する"""
    year = st.session_state.current_date.year
    month = st.session_state.current_date.month
    month_id = f"{year}-{month:02d}"

    events, day_status, is_month_locked, _ = get_firestore_data(year, month)

    header_cols = st.columns([1, 2, 1])
    if header_cols[0].button("<< 前の月"):
        st.session_state.current_date -= relativedelta(months=1)
        st.rerun()
    header_cols[1].header(f"{year}年 {month}月")
    if header_cols[2].button("次の月 >>"):
        st.session_state.current_date += relativedelta(months=1)
        st.rerun()

    if is_month_locked:
        st.error("🔒 この月はロックされているため、シフトの編集や掲示板への書き込みはできません。")

    cal = calendar.monthcalendar(year, month)
    days_of_week = ["月", "火", "水", "木", "金", "土", "日"]
    
    st.divider()

    for week in cal:
        cols = st.columns(7)
        for i, day in enumerate(week):
            if day == 0:
                cols[i].write("")
                continue
            
            day_name = days_of_week[i]
            date_str = f"{month_id}-{day:02d}"
            is_held = day_status.get(date_str, {}).get('isHeld', False)
            
            with cols[i].container(border=True):
                color = "red" if day_name == "日" else "blue" if day_name == "土" else "inherit"
                st.markdown(f"<p style='color:{color}; margin-bottom:0; text-align:center;'><strong>{day}</strong> ({day_name})</p>", unsafe_allow_html=True)

                if st.session_state.admin_mode:
                    new_is_held = st.checkbox("開催", value=is_held, key=f"held_{date_str}", disabled=is_month_locked)
                    if new_is_held != is_held:
                        db.collection(DAY_STATUS_COLLECTION).document(date_str).set({'isHeld': new_is_held, 'month_id': month_id})
                        st.cache_data.clear(); st.rerun()
                elif is_held:
                    st.success("開催日")

                day_events = [data for data in events.values() if data.get('date') == date_str]
                for event in day_events:
                    doc_id = [k for k, v in events.items() if v == event][0]
                    shift_cols = st.columns([3, 1])
                    if event.get('name') == st.session_state.user_name:
                        shift_cols[0].info(f"👤 {event.get('name')}")
                    else:
                        shift_cols[0].write(f"👤 {event.get('name')}")
                    
                    # 【修正点1】管理者なら自分以外のシフトも削除可能に
                    if (event.get('name') == st.session_state.user_name or st.session_state.admin_mode) and not is_month_locked:
                        if shift_cols[1].button("✖️", key=f"del_{doc_id}", help="シフトを削除"):
                            db.collection(EVENTS_COLLECTION).document(doc_id).delete()
                            st.cache_data.clear(); st.rerun()
                
                if is_held and not is_month_locked:
                    if len(day_events) < MAX_SHIFTS_PER_DAY:
                        # 【修正点2】管理者の場合は「代理入力フォーム」を表示
                        if st.session_state.admin_mode:
                            with st.form(key=f"admin_add_form_{date_str}"):
                                admin_add_name = st.text_input("代理入力", key=f"admin_name_{date_str}", label_visibility="collapsed", placeholder="名前を入力")
                                if st.form_submit_button("追加"):
                                    if admin_add_name:
                                        new_event = {
                                            'date': date_str, 'month_id': month_id,
                                            'name': admin_add_name,
                                            'createdAt': firestore.SERVER_TIMESTAMP,
                                            'uid': str(uuid.uuid4())
                                        }
                                        db.collection(EVENTS_COLLECTION).add(new_event)
                                        st.cache_data.clear(); st.rerun()
                        # 通常ユーザーの場合はこれまで通りのボタンを表示
                        else:
                            if st.button("シフトに入る", key=f"add_{date_str}"):
                                is_already_in = any(e['name'] == st.session_state.user_name for e in day_events)
                                if not is_already_in:
                                    new_event = {
                                        'date': date_str, 'month_id': month_id,
                                        'name': st.session_state.user_name,
                                        'createdAt': firestore.SERVER_TIMESTAMP,
                                        'uid': str(uuid.uuid4())
                                    }
                                    db.collection(EVENTS_COLLECTION).add(new_event)
                                    st.cache_data.clear(); st.rerun()
                                else:
                                    st.warning("すでに入っています。")
                    else:
                        st.warning("満員です")

def show_board_and_info():
    """掲示板と説明セクションを表示する"""
    year = st.session_state.current_date.year
    month = st.session_state.current_date.month
    month_id = f"{year}-{month:02d}"
    _, _, is_month_locked, board_messages = get_firestore_data(year, month)

    st.divider()
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📢 緊急連絡掲示板")
        st.info("💡 投稿から2週間が経過したメッセージは自動的に削除されます。")
        
        with st.form("board_form", clear_on_submit=True):
            name_input = st.text_input("お名前", value=st.session_state.user_name, disabled=is_month_locked)
            message_input = st.text_area("メッセージ", disabled=is_month_locked)
            if st.form_submit_button("書き込む", disabled=is_month_locked):
                if name_input and message_input:
                    new_message = {
                        'month_id': month_id, 'name': name_input,
                        'message': message_input, 'timestamp': firestore.SERVER_TIMESTAMP
                    }
                    db.collection(BOARD_COLLECTION).add(new_message)
                    st.cache_data.clear(); st.rerun()
                else:
                    st.warning("お名前とメッセージを入力してください。")
        
        for msg in board_messages:
            ts = msg.get('timestamp')
            timestamp_str = ts.strftime('%Y-%m-%d %H:%M') if ts and hasattr(ts, 'strftime') else "時刻不明"
            st.markdown(f"""
            <div style="border-bottom: 1px solid #e0e0e0; padding-bottom: 8px; margin-bottom: 8px;">
                <p style="margin: 0;"><strong>{msg.get('name')}</strong> <small>({timestamp_str})</small></p>
                <p style="margin: 0; white-space: pre-wrap;">{msg.get('message')}</p>
            </div>
            """, unsafe_allow_html=True)

    with col2:
        st.subheader("💡 ご利用上のルール")
        # 【修正点3】管理者による調整の可能性について追記
        st.warning("""
        - シフトは「早いもの勝ち」で決めていきます。
        - 2名以上の参加がない場合は、開催を取り消すことがあります。
        - **管理者が調整のため、シフトの追加や削除を行う場合があります。シフト確定後は、ご自身で最終確認をお願いします。**
        """)

def show_admin_sidebar():
    """管理者用のサイドバーと機能を表示する"""
    with st.sidebar:
        st.title("🛠️ 管理者メニュー")
        
        if not st.session_state.admin_mode:
            password = st.text_input("パスワード", type="password")
            if st.button("ログイン"):
                if password == st.secrets["admin"]["password"]:
                    st.session_state.admin_mode = True; st.rerun()
                else:
                    st.error("パスワードが違います。")
        
        if st.session_state.admin_mode:
            st.success("管理者としてログイン中")
            if st.button("ログアウト"):
                st.session_state.admin_mode = False; st.rerun()

            st.divider()

            year = st.session_state.current_date.year
            month = st.session_state.current_date.month
            month_id = f"{year}-{month:02d}"
            _, _, is_month_locked, _ = get_firestore_data(year, month)
            st.subheader("月のロック管理")
            if is_month_locked:
                if st.button(f"{month}月をロック解除"):
                    db.collection(MONTH_LOCKS_COLLECTION).document(month_id).set({'isLocked': False})
                    st.cache_data.clear(); st.rerun()
            else:
                if st.button(f"🔴 {month}月をロックする"):
                    db.collection(MONTH_LOCKS_COLLECTION).document(month_id).set({'isLocked': True})
                    st.cache_data.clear(); st.rerun()

            st.divider()

            with st.expander("📊 シフト回数集計", expanded=False):
                today = datetime.now()
                start_date = st.date_input("開始日", today - relativedelta(months=3))
                end_date = st.date_input("終了日", today)
                if st.button("集計する"):
                    perform_aggregation(start_date, end_date)

def perform_aggregation(start_date, end_date):
    """シフト集計を実行し、結果を表示・ダウンロード可能にする"""
    with st.spinner("集計中..."):
        all_events = [doc.to_dict() for doc in db.collection(EVENTS_COLLECTION).stream()]
        all_day_status = {doc.id: doc.to_dict() for doc in db.collection(DAY_STATUS_COLLECTION).stream()}
        
        filtered_events = [
            event for event in all_events
            if start_date <= datetime.strptime(event['date'], '%Y-%m-%d').date() <= end_date
            and all_day_status.get(event['date'], {}).get('isHeld', False)
        ]
        
        if not filtered_events:
            st.warning("指定期間に該当する開催日のシフトデータがありません。"); return
            
        df = pd.DataFrame(filtered_events)
        df['month'] = pd.to_datetime(df['date']).dt.to_period('M')
        
        pivot = df.pivot_table(index='name', columns='month', values='uid', aggfunc='count', fill_value=0)
        pivot['合計'] = pivot.sum(axis=1)
        
        st.subheader("シフト回数集計結果")
        st.dataframe(pivot)
        
        csv = pivot.to_csv().encode('utf-8-sig')
        st.download_button(
            label="CSVダウンロード", data=csv,
            file_name=f"shift_report_{start_date}_to_{end_date}.csv", mime="text/csv"
        )

# --- メイン実行部分 ---
if __name__ == "__main__":
    st.title("🗓️ 見守りシフト管理カレンダー")
    st.caption("管理者の方は、画面左上の「>」をクリックしてメニューを開いてください。")
    
    show_admin_sidebar()

    if 'cleanup_done' not in st.session_state:
        cleanup_old_board_messages()
        st.session_state.cleanup_done = True

    if not st.session_state.user_name:
        show_welcome_and_name_input()
    else:
        show_main_app()
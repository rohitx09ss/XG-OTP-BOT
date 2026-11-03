import os, io, time, html, logging, threading
from datetime import datetime, timezone
import requests
import qrcode
from PIL import Image
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError
import telebot
from telebot import types

BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
MONGODB_URI = os.environ['MONGODB_URI']
API_URL = os.getenv('OTP_API_URL', 'https://YOUR-VERCEL-DOMAIN.vercel.app/api').rstrip('/')
FAMWAY_BASE = os.getenv('FAMWAY_BASE_URL', 'https://famway.onrender.com').rstrip('/')
FAMWAY_KEY = os.environ['FAMWAY_API_KEY']
ADMIN_IDS = {int(x.strip()) for x in os.getenv('ADMIN_IDS','').split(',') if x.strip().isdigit()}
SUPPORT_USERNAME = os.getenv('SUPPORT_USERNAME','')
LOGO_PATH = os.getenv('LOGO_PATH', os.path.join(os.path.dirname(__file__),'..','assets','xg-logo.png'))
MIN_TOPUP, MAX_TOPUP = 10, 10000
COUNTRIES_PER_PAGE, NUMBERS_PER_PAGE = 12, 10
HTTP = requests.Session()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('xg-otp')

mongo = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=15000)
db = mongo['xg_otp_bot']
users, wallets = db.users, db.wallets
payments, transactions, orders = db.payments, db.transactions, db.orders
settings, promos, referrals = db.settings, db.promos, db.referrals
payments.create_index([('order_id', ASCENDING)], unique=True)
transactions.create_index([('tx_id', ASCENDING)], unique=True)
orders.create_index([('order_id', ASCENDING)], unique=True)
users.create_index([('telegram_id', ASCENDING)], unique=True)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML', threaded=True)
flow = {}  # short-lived chat input state; durable money/order state is in MongoDB
country_cache = {'at':0,'data':[]}

# ---------------- shared helpers ----------------
def now(): return datetime.now(timezone.utc)
def is_admin(uid): return uid in ADMIN_IDS
def money(v): return f'₹{float(v):,.2f}'
def flag(code): return ''.join(chr(127397+ord(c)) for c in code[:2].upper())
def esc(s): return html.escape(str(s))
def ensure_user(u):
    users.update_one({'telegram_id':u.id},{'$setOnInsert':{'telegram_id':u.id,'name':u.first_name or '', 'username':u.username or '', 'created_at':now(),'blocked':False},'$set':{'last_seen':now(),'name':u.first_name or '', 'username':u.username or ''}},upsert=True)
    wallets.update_one({'telegram_id':u.id},{'$setOnInsert':{'balance':0.0}},upsert=True)
def balance(uid):
    d=wallets.find_one({'telegram_id':uid}) or {}
    return float(d.get('balance',0))
def user_blocked(uid):
    d=users.find_one({'telegram_id':uid}) or {}
    return bool(d.get('blocked'))
def api_get(path, params=None):
    r=HTTP.get(f'{API_URL}/{path.lstrip("/")}',params=params,timeout=25)
    r.raise_for_status(); return r.json()
def famway_headers(): return {'X-Api-Key':FAMWAY_KEY,'Accept':'application/json','Content-Type':'application/json'}
def home_kb(uid):
    k=types.InlineKeyboardMarkup(row_width=2)
    k.row(types.InlineKeyboardButton('🌍 Select Country',callback_data='countries:1'),types.InlineKeyboardButton('💳 Add Funds',callback_data='topup'))
    k.row(types.InlineKeyboardButton('👛 My Balance',callback_data='balance'),types.InlineKeyboardButton('📦 My Orders',callback_data='myorders:1'))
    k.row(types.InlineKeyboardButton('🧾 Transactions',callback_data='history:1'),types.InlineKeyboardButton('👤 My Profile',callback_data='profile'))
    k.row(types.InlineKeyboardButton('🎁 Referral & Promo',callback_data='referral'),types.InlineKeyboardButton('🆘 Help / Support',callback_data='support'))
    if is_admin(uid): k.row(types.InlineKeyboardButton('🛡 Admin Panel',callback_data='admin'))
    return k
def home_text(uid):
    u=users.find_one({'telegram_id':uid}) or {}
    return (f'<b>⚡ XG OTP BOT</b>\nWelcome, {esc(u.get("name") or "User")}!\n\n'
            f'👛 <b>Wallet:</b> {money(balance(uid))}\n🧪 <b>Mode:</b> Sandbox / Test only\n\nChoose an option below.')
def edit_or_send(q, text, kb=None):
    try: bot.edit_message_text(text,q.message.chat.id,q.message.message_id,reply_markup=kb)
    except Exception: bot.send_message(q.message.chat.id,text,reply_markup=kb)
def get_countries():
    if not country_cache['data'] or time.time()-country_cache['at']>300:
        data=api_get('countries')
        country_cache['data']=data if isinstance(data,list) else data.get('countries',[])
        country_cache['at']=time.time()
    return country_cache['data']
def countries_kb(page=1):
    data=get_countries(); pages=max(1,(len(data)+COUNTRIES_PER_PAGE-1)//COUNTRIES_PER_PAGE); page=max(1,min(page,pages))
    chunk=data[(page-1)*COUNTRIES_PER_PAGE:page*COUNTRIES_PER_PAGE]
    k=types.InlineKeyboardMarkup(row_width=2)
    for i in range(0,len(chunk),2):
        row=[]
        for c in chunk[i:i+2]: row.append(types.InlineKeyboardButton(f'{flag(c["code"])} {c["name"]} · {money(c["price"])}',callback_data='country:'+c['code']))
        k.row(*row)
    nav=[]
    if page>1: nav.append(types.InlineKeyboardButton('‹ Previous',callback_data=f'countries:{page-1}'))
    nav.append(types.InlineKeyboardButton(f'{page}/{pages}',callback_data='noop'))
    if page<pages: nav.append(types.InlineKeyboardButton('Next ›',callback_data=f'countries:{page+1}'))
    k.row(*nav); k.row(types.InlineKeyboardButton('🏠 Home',callback_data='home'))
    return k

def number_page(uid, code, page):
    c=next((x for x in get_countries() if x['code']==code),None)
    if not c: raise ValueError('Country not found')
    key=f'{uid}:{code}:{page}'
    cache=flow.setdefault(uid,{})
    if cache.get('number_page_key')!=key:
        d=api_get('number',{'country':code,'count':NUMBERS_PER_PAGE})
        nums=d.get('numbers') or ([d['number']] if d.get('number') else [])
        cache['number_page_key']=key; cache['number_page']=nums
    nums=cache.get('number_page',[])
    k=types.InlineKeyboardMarkup(row_width=1)
    for idx,n in enumerate(nums): k.add(types.InlineKeyboardButton('📱 '+n,callback_data=f'choose:{code}:{page}:{idx}'))
    nav=[]
    if page>1: nav.append(types.InlineKeyboardButton('‹ Previous',callback_data=f'numbers:{code}:{page-1}'))
    nav.append(types.InlineKeyboardButton(f'Page {page}',callback_data='noop'))
    nav.append(types.InlineKeyboardButton('Next ›',callback_data=f'numbers:{code}:{page+1}'))
    k.row(*nav); k.row(types.InlineKeyboardButton('⬅️ Countries',callback_data='countries:1'))
    return c,nums,k

def make_qr(upi_intent):
    qr=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H,box_size=10,border=4)
    qr.add_data(upi_intent); qr.make(fit=True)
    img=qr.make_image(fill_color='black',back_color='white').convert('RGB')
    if os.path.exists(LOGO_PATH):
        logo=Image.open(LOGO_PATH).convert('RGBA')
        # fit logo into a white quiet-zone tile so the QR remains scannable
        side=img.width//5; logo.thumbnail((side-16,side-16))
        tile=Image.new('RGBA',(side,side),'white')
        tile.alpha_composite(logo,((side-logo.width)//2,(side-logo.height)//2))
        img=img.convert('RGBA'); img.alpha_composite(tile,((img.width-side)//2,(img.height-side)//2)); img=img.convert('RGB')
    b=io.BytesIO(); img.save(b,format='PNG'); b.seek(0); return b

def credit_payment(order_id, uid, amount, utr=''):
    # MongoDB Atlas transaction: unique order + ledger + wallet update are atomic.
    with mongo.start_session() as s:
        with s.start_transaction():
            p=payments.find_one({'order_id':order_id},session=s)
            if not p or p.get('credited'): return False
            payments.update_one({'order_id':order_id,'credited':{'$ne':True}}, {'$set':{'credited':True,'status':'success','utr':utr,'verified_at':now()}},session=s)
            wallets.update_one({'telegram_id':uid},{'$inc':{'balance':float(amount)}},upsert=True,session=s)
            transactions.insert_one({'tx_id':'topup:'+order_id,'telegram_id':uid,'type':'credit','amount':float(amount),'reason':'FamWay verified top-up','order_id':order_id,'created_at':now()},session=s)
    return True

def famway_check(order_id):
    r=HTTP.get(FAMWAY_BASE+'/api/checkout-status',params={'order_id':order_id},timeout=35); r.raise_for_status(); return r.json()
def famway_verify(order_id):
    r=HTTP.get(FAMWAY_BASE+'/api/verify-order',params={'order_id':order_id},headers=famway_headers(),timeout=35); r.raise_for_status(); return r.json()

# ---------------- commands and user panel ----------------
@bot.message_handler(commands=['start','menu'])
def start(m):
    ensure_user(m.from_user)
    if user_blocked(m.from_user.id): return bot.reply_to(m,'Your account is restricted. Contact support.')
    bot.send_message(m.chat.id,home_text(m.from_user.id),reply_markup=home_kb(m.from_user.id))
@bot.message_handler(commands=['cancel'])
def cancel(m):
    flow.pop(m.from_user.id,None); bot.send_message(m.chat.id,'Cancelled.',reply_markup=home_kb(m.from_user.id))
@bot.message_handler(commands=['admin'])
def admin_cmd(m):
    if not is_admin(m.from_user.id): return
    bot.send_message(m.chat.id,'<b>Admin commands</b>\n/addbalance TELEGRAM_ID AMOUNT\n/block TELEGRAM_ID\n/unblock TELEGRAM_ID\n/stats\n/broadcast MESSAGE')
@bot.message_handler(commands=['stats'])
def stats(m):
    if not is_admin(m.from_user.id): return
    bot.reply_to(m,f'Users: {users.count_documents({})}\nOrders: {orders.count_documents({})}\nPayments: {payments.count_documents({})}')
@bot.message_handler(commands=['addbalance'])
def addbalance_cmd(m):
    if not is_admin(m.from_user.id): return
    try:
        _,uid,amt=m.text.split(); uid=int(uid); amt=float(amt)
        if amt<=0 or amt>100000: raise ValueError()
        wallets.update_one({'telegram_id':uid},{'$inc':{'balance':amt}},upsert=True)
        tx='admin-credit:'+str(m.message_id)+':'+str(uid)
        transactions.insert_one({'tx_id':tx,'telegram_id':uid,'type':'credit','amount':amt,'reason':f'Admin {m.from_user.id}','created_at':now()})
        bot.reply_to(m,'Balance updated.')
    except Exception: bot.reply_to(m,'Usage: /addbalance TELEGRAM_ID AMOUNT')
@bot.message_handler(commands=['block','unblock'])
def block_cmd(m):
    if not is_admin(m.from_user.id): return
    try:
        uid=int(m.text.split()[1]); users.update_one({'telegram_id':uid},{'$set':{'blocked':m.text.startswith('/block')}})
        bot.reply_to(m,'User status updated.')
    except Exception: bot.reply_to(m,'Usage: /block TELEGRAM_ID')
@bot.message_handler(commands=['broadcast'])
def broadcast_cmd(m):
    if not is_admin(m.from_user.id): return
    msg=m.text.partition(' ')[2].strip()
    if not msg: return bot.reply_to(m,'Usage: /broadcast message')
    sent=failed=0
    for u in users.find({'blocked':{'$ne':True}},{'telegram_id':1}):
        try: bot.send_message(u['telegram_id'],msg); sent+=1
        except Exception: failed+=1
    bot.reply_to(m,f'Broadcast finished. Sent: {sent}, failed: {failed}')

@bot.callback_query_handler(func=lambda q: True)
def callbacks(q):
    uid=q.from_user.id; ensure_user(q.from_user)
    if user_blocked(uid): return bot.answer_callback_query(q.id,'Account restricted')
    data=q.data
    try:
        if data=='noop': return bot.answer_callback_query(q.id)
        if data=='home': return edit_or_send(q,home_text(uid),home_kb(uid))
        if data=='balance': return edit_or_send(q,f'<b>👛 My Balance</b>\n{money(balance(uid))}',types.InlineKeyboardMarkup().add(types.InlineKeyboardButton('➕ Add Funds',callback_data='topup'),types.InlineKeyboardButton('🏠 Home',callback_data='home')))
        if data=='topup':
            flow[uid]={'awaiting':'topup_amount'}
            bot.send_message(q.message.chat.id,f'Enter amount in INR (minimum {money(MIN_TOPUP)}, maximum {money(MAX_TOPUP)}).')
            return bot.answer_callback_query(q.id)
        if data.startswith('countries:'):
            page=int(data.split(':')[1]); edit_or_send(q,'<b>🌍 Select Country</b>\nChoose a sandbox test-number format:',countries_kb(page)); return bot.answer_callback_query(q.id)
        if data.startswith('country:'):
            code=data.split(':',1)[1]; c,nums,k=number_page(uid,code,1)
            edit_or_send(q,f'{flag(code)} <b>{esc(c["name"])}</b> · {money(c["price"])}\n\n10 generated <b>test candidates</b> per page. Select one:',k); return bot.answer_callback_query(q.id)
        if data.startswith('numbers:'):
            _,code,p=data.split(':'); c,nums,k=number_page(uid,code,int(p))
            edit_or_send(q,f'{flag(code)} <b>{esc(c["name"])}</b> · {money(c["price"])}\n\nPage {p}: generated test candidates:',k); return bot.answer_callback_query(q.id)
        if data.startswith('choose:'):
            _,code,p,idx=data.split(':'); c,nums,k=number_page(uid,code,int(p)); n=nums[int(idx)]
            oid=f'TEST-{uid}-{int(time.time())}-{int(idx)}'; price=float(c['price'])
            flow[uid]={'pending_buy':{'order_id':oid,'code':code,'country':c['name'],'number':n,'price':price}}
            kb=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton(f'Confirm · {money(price)}',callback_data='buyconfirm'),types.InlineKeyboardButton('Cancel',callback_data='home'))
            edit_or_send(q,f'<b>Confirm test order</b>\nCountry: {esc(c["name"])}\nTest candidate: <code>{esc(n)}</code>\nPrice: <b>{money(price)}</b>\nWallet: {money(balance(uid))}\n\nThis is a generated test candidate, not a provisioned live phone number.',kb); return bot.answer_callback_query(q.id)
        if data=='buyconfirm':
            p=flow.get(uid,{}).get('pending_buy')
            if not p: return bot.answer_callback_query(q.id,'Order expired. Start again.')
            oid=p['order_id']; price=p['price']
            with mongo.start_session() as s:
                with s.start_transaction():
                    res=wallets.update_one({'telegram_id':uid,'balance':{'$gte':price}},{'$inc':{'balance':-price}},session=s)
                    if res.modified_count!=1: raise ValueError('Insufficient balance')
                    orders.insert_one({'order_id':oid,'telegram_id':uid,'country_code':p['code'],'country':p['country'],'number':p['number'],'price':price,'status':'test_ready','mode':'sandbox','created_at':now()},session=s)
                    transactions.insert_one({'tx_id':'debit:'+oid,'telegram_id':uid,'type':'debit','amount':price,'reason':'Sandbox test candidate purchase','order_id':oid,'created_at':now()},session=s)
            flow[uid].pop('pending_buy',None)
            k=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton('🔎 Check OTP (Sandbox)',callback_data='checkotp:'+oid))
            bot.send_message(q.message.chat.id,f'✅ <b>Test order created</b>\nOrder: <code>{oid}</code>\nCandidate: <code>{esc(p["number"])}</code>\nRemaining wallet: {money(balance(uid))}\n\nTap below to request a clearly labelled test OTP.',reply_markup=k)
            return bot.answer_callback_query(q.id,'Purchased')
        if data.startswith('checkotp:'):
            oid=data.split(':',1)[1]; o=orders.find_one({'order_id':oid,'telegram_id':uid})
            if not o: return bot.answer_callback_query(q.id,'Order not found')
            if o.get('otp'): return bot.send_message(q.message.chat.id,f'🧪 <b>Sandbox OTP</b>\n<code>{esc(o["otp"])}</code>\nOrder: <code>{oid}</code>')
            # Existing endpoint generates a random dummy code on demand; never a real SMS.
            result=api_get('otp',{'number':o['number']})
            otp=str(result.get('otp',''))
            if not otp: raise RuntimeError('Test API did not return an OTP')
            orders.update_one({'order_id':oid,'telegram_id':uid,'otp':{'$exists':False}},{'$set':{'otp':otp,'otp_requested_at':now(),'status':'test_otp_returned'}})
            fresh=orders.find_one({'order_id':oid})
            bot.send_message(q.message.chat.id,f'🧪 <b>Sandbox/Test OTP</b>\n<code>{esc(fresh.get("otp",otp))}</code>\n\nThis code is generated for testing only; it is not an incoming SMS.\nOrder: <code>{oid}</code>')
            return bot.answer_callback_query(q.id,'Test response received')
        if data.startswith('myorders:'):
            page=int(data.split(':')[1]); cur=list(orders.find({'telegram_id':uid}).sort('created_at',-1).skip((page-1)*8).limit(8))
            if not cur: txt='No orders yet.'
            else: txt='<b>📦 My Orders</b>\n'+'\n'.join(f'• <code>{esc(x["order_id"])}</code> · {esc(x["status"])} · {money(x["price"])}' for x in cur)
            k=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton('‹',callback_data=f'myorders:{max(1,page-1)}'),types.InlineKeyboardButton('›',callback_data=f'myorders:{page+1}')).add(types.InlineKeyboardButton('🏠 Home',callback_data='home'))
            edit_or_send(q,txt,k); return bot.answer_callback_query(q.id)
        if data.startswith('history:'):
            cur=list(transactions.find({'telegram_id':uid}).sort('created_at',-1).limit(10))
            txt='<b>🧾 Recent Transactions</b>\n'+('\n'.join(f'• {x["type"]}: {money(x["amount"])} — {esc(x.get("reason",""))}' for x in cur) if cur else 'No transactions yet.')
            edit_or_send(q,txt,types.InlineKeyboardMarkup().add(types.InlineKeyboardButton('🏠 Home',callback_data='home'))); return bot.answer_callback_query(q.id)
        if data=='profile':
            u=users.find_one({'telegram_id':uid}) or {}; txt=f'<b>👤 My Profile</b>\nName: {esc(u.get("name",""))}\nUsername: @{esc(u.get("username") or "not set")}\nTelegram ID: <code>{uid}</code>\nWallet: {money(balance(uid))}'
            edit_or_send(q,txt,types.InlineKeyboardMarkup().add(types.InlineKeyboardButton('🏠 Home',callback_data='home'))); return bot.answer_callback_query(q.id)
        if data=='referral':
            code=f'XG{uid}'; referrals.update_one({'telegram_id':uid},{'$setOnInsert':{'telegram_id':uid,'code':code,'created_at':now()}},upsert=True)
            edit_or_send(q,f'<b>🎁 Referral</b>\nYour referral code: <code>{code}</code>\nReferral rewards can be enabled by admin after configuring abuse limits.\nPromo codes: ask support for active offers.',types.InlineKeyboardMarkup().add(types.InlineKeyboardButton('🏠 Home',callback_data='home'))); return bot.answer_callback_query(q.id)
        if data=='support':
            txt=('Support: @'+SUPPORT_USERNAME) if SUPPORT_USERNAME else 'Please contact the bot administrator.'
            edit_or_send(q,txt,types.InlineKeyboardMarkup().add(types.InlineKeyboardButton('🏠 Home',callback_data='home'))); return bot.answer_callback_query(q.id)
        if data=='admin' and is_admin(uid):
            txt=f'<b>🛡 Admin Panel</b>\nUsers: {users.count_documents({})}\nOrders: {orders.count_documents({})}\nPayments: {payments.count_documents({})}\nWallet liabilities: {money(sum((x.get("balance",0) for x in wallets.find({}, {"balance":1})),0))}\n\nCommands: /addbalance /block /unblock /stats /broadcast'
            edit_or_send(q,txt,types.InlineKeyboardMarkup().add(types.InlineKeyboardButton('🏠 Home',callback_data='home'))); return bot.answer_callback_query(q.id)
        if data.startswith('paycheck:'):
            order_id=data.split(':',1)[1]; p=payments.find_one({'order_id':order_id,'telegram_id':uid})
            if not p: return bot.answer_callback_query(q.id,'Payment not found')
            st=famway_check(order_id)
            if st.get('status')=='success':
                ver=famway_verify(order_id); vdata=ver.get('data',ver)
                if vdata.get('status')!='success': return bot.answer_callback_query(q.id,'Final verification pending')
                if credit_payment(order_id,uid,p['amount'],vdata.get('utr','')):
                    bot.send_message(q.message.chat.id,f'✅ <b>Payment verified!</b>\nCredited: {money(p["amount"])}\nWallet: {money(balance(uid))}\nUTR: <code>{esc(vdata.get("utr",""))}</code>')
                else: bot.send_message(q.message.chat.id,'Payment was already credited or is being processed.')
            elif st.get('status') in ('detected','review'):
                bot.send_message(q.message.chat.id,'⏳ Payment detected / under review. Wallet credit tabhi hoga jab final status success ho.')
            elif st.get('status')=='expired': bot.send_message(q.message.chat.id,'Payment order expired. Please create a new top-up order.')
            else: bot.send_message(q.message.chat.id,'Payment pending. Pay the exact amount shown and check again.')
            return bot.answer_callback_query(q.id,'Status checked')
    except ValueError as e:
        bot.answer_callback_query(q.id,str(e)[:180],show_alert=True)
    except Exception as e:
        log.exception('callback failed'); bot.answer_callback_query(q.id,'Temporary error. Try again.',show_alert=True)

@bot.message_handler(content_types=['text'])
def text_input(m):
    uid=m.from_user.id; ensure_user(m.from_user)
    st=flow.get(uid,{})
    if st.get('awaiting')=='topup_amount':
        try:
            amount=float(m.text.strip())
            if amount!=int(amount) or not MIN_TOPUP<=amount<=MAX_TOPUP: raise ValueError()
            resp=HTTP.post(FAMWAY_BASE+'/api/create-order',headers=famway_headers(),json={'amount':int(amount),'customer_name':m.from_user.first_name or 'XG user'},timeout=90)
            body=resp.json()
            if resp.status_code!=200 or body.get('status')!='success': raise RuntimeError(body.get('message','FamWay order creation failed'))
            d=body['data']; order_id=d['order_id']; payable=float(d['payable_amount'])
            payments.insert_one({'order_id':order_id,'telegram_id':uid,'amount':payable,'requested_amount':amount,'status':'pending','credited':False,'created_at':now(),'expires_at':d.get('expires_at')})
            qr=make_qr(d['upi_intent'])
            k=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton('🌐 Open FamWay Checkout',url=d['checkout_url'])).add(types.InlineKeyboardButton('✅ Check Payment',callback_data='paycheck:'+order_id))
            bot.send_photo(m.chat.id,qr,caption=f'<b>⚡ XG OTP BOT — Add Funds</b>\nPay exactly: <b>{money(payable)}</b>\nRequested: {money(amount)}\nOrder: <code>{esc(order_id)}</code>\n\nScan this custom QR or open checkout. Wallet credit happens only after server-side verified SUCCESS. Order expires in 5 minutes.',reply_markup=k)
            flow.pop(uid,None)
        except ValueError: bot.reply_to(m,f'Enter a whole INR amount between {MIN_TOPUP} and {MAX_TOPUP}.')
        except Exception as e: log.exception('topup create failed'); bot.reply_to(m,'Could not create payment order. Check gateway settings and try again.')
    else:
        bot.send_message(m.chat.id,home_text(uid),reply_markup=home_kb(uid))

if __name__=='__main__':
    mongo.admin.command('ping')
    log.info('XG OTP BOT starting; sandbox OTP mode only')
    bot.infinity_polling(skip_pending=True,timeout=30,long_polling_timeout=30)

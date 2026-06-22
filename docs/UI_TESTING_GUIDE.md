# BharatBot UI Testing Guide

## Quick Start

### 1. **Start Backend**
```bash
cd C:\FlyingRaijin\INVISBL\practice\Tata Motors\poc_v6_with_pipecat_and_websocket
python -m uvicorn mainV2:app --reload --host 0.0.0.0 --port 8000
```

### 2. **Open Frontend**
```
http://localhost:8000/bharatbot_ui2.html
```
(Or serve the HTML file directly if backend serves static files)

### 3. **Configure API URL**
In `bharatbot_ui2.html`, update line ~610:
```javascript
const API = 'http://localhost:8000';  // Change from '' to your backend URL
```

---

## Test Scenarios

### Scenario 1: Fresh User Signup
**Steps:**
1. Open UI, see "Sign In" modal
2. Click "Sign up"
3. Fill form:
   - Name: "John Doe"
   - Email: "john@test.com"
   - Password: "SecurePass123!"
4. Click "Create Account"

**Expected:**
- ✅ Modal closes
- ✅ User avatar appears in sidebar with initials "JD"
- ✅ Empty sessions list shown
- ✅ Toast: "Welcome, John Doe!"

**Failure modes to watch:**
- ❌ "Email already exists" — duplicate email
- ❌ Password policy errors — doesn't meet requirements
- ❌ Invalid email format — email validation failed

---

### Scenario 2: Password Validation
**Steps:**
1. Try signup with weak passwords
   - "weak" → should fail (8+ chars)
   - "weakpassword" → should fail (no digit)
   - "WeakPassword" → should fail (no special char)
   - "weak@Password" → should fail (no digit)
   - "Weak@Pass1" → should succeed ✓

**Expected:**
- ✅ Each violation shown below password field
- ✅ Form disabled until password is fixed
- ✅ Policy checklist shown during signup

---

### Scenario 3: Login After Signup
**Steps:**
1. Complete signup
2. Click user avatar in sidebar
3. Click "🚪 Logout"
4. See "Sign In" modal
5. Enter:
   - Email: "john@test.com"
   - Password: "SecurePass123!"
6. Click "Sign In"

**Expected:**
- ✅ Logged in successfully
- ✅ Avatar reappears with user info
- ✅ Previous sessions loaded
- ✅ Toast: "Welcome!"

**Failure modes:**
- ❌ "Invalid email or password" — wrong credentials
- ❌ No visible error — API down

---

### Scenario 4: Create Conversation
**Steps:**
1. Log in as user
2. Click "New conversation" button
3. See new conversation in left sidebar
4. Click it
5. Type: "Hello, how are you?"
6. Press Enter or click send

**Expected:**
- ✅ User message appears with language tags
- ✅ Bot loading indicator shows
- ✅ Bot response appears
- ✅ WebSocket indicator shows "connected" (green dot)

**Failure modes:**
- ❌ "Not authenticated" — token not sent
- ❌ 403 Forbidden — session doesn't belong to user
- ❌ No response — pipeline failed

---

### Scenario 5: Voice Message
**Steps:**
1. In active conversation, click mic button
2. Speak: "नमस्ते"
3. Click mic again to stop
4. See user transcript
5. Wait for bot response

**Expected:**
- ✅ Recording indicator shows
- ✅ Timer counts up
- ✅ Recording stops on button click
- ✅ User bubble shows language tag "HI"
- ✅ Bot response in detected language

**Failure modes:**
- ❌ "Microphone access denied" — browser permissions
- ❌ Recording sends but no response — pipeline error

---

### Scenario 6: Token Expiry (15 min timeout)
**Steps:**
1. Set `ACCESS_TOKEN_EXPIRE_MINUTES=0.1` (6 seconds) on backend for testing
2. Log in
3. Wait 6+ seconds
4. Try to send message

**Expected:**
- ✅ 401 response received
- ✅ Automatic token refresh attempt
- ✅ Message sent successfully (no user action needed)
- ✅ Access token updated in localStorage

**Failure modes:**
- ❌ "Session expired" error — refresh token not working
- ❌ Stuck loading — timeout not handled

---

### Scenario 7: Session Ownership
**Steps:**
1. User A: Create session "A-Session-1" with ID: `abc123`
2. User A: Add message "Hello from A"
3. User A: Log out
4. User B: Log in
5. User B: Try to access `abc123` (modify URL or localStorage)

**Expected:**
- ✅ 404 or 403 error
- ✅ UI shows "Session not found" or "Access denied"
- ✅ Session doesn't appear in User B's list

**Failure modes:**
- ❌ User B sees User A's sessions
- ❌ User B can send messages to User A's session

---

### Scenario 8: Change Password
**Steps:**
1. Log in as user
2. Click user avatar → "🔐 Change password"
3. Enter:
   - Current: "SecurePass123!"
   - New: "NewSecure456@"
   - Confirm: "NewSecure456@"
4. Click "Change Password"

**Expected:**
- ✅ Toast: "Password changed successfully!"
- ✅ Automatically logged out
- ✅ All other sessions logged out
- ✅ Auth modal shows
- ✅ Can log in with new password

**Failure modes:**
- ❌ "Invalid current password" — wrong current password
- ❌ Password doesn't meet policy — new password weak
- ❌ Mismatch error — confirm doesn't match new

---

### Scenario 9: Multiple Users Concurrent
**Steps:**
1. Open two browser tabs
2. Tab 1: User A logs in, creates session
3. Tab 2: User B logs in (same machine)
4. Tab 1: User A sends message "From A"
5. Tab 2: User B creates own session
6. Both users send messages

**Expected:**
- ✅ Each user's sessions isolated
- ✅ Messages don't cross-contaminate
- ✅ WebSocket connections independent
- ✅ No token conflicts

**Failure modes:**
- ❌ User B sees User A's messages
- ❌ Token conflict (one overwrites the other)
- ❌ WebSocket connection drops for one user

---

### Scenario 10: Delete Conversation
**Steps:**
1. Create conversation "To Delete"
2. Add message
3. Hover over session in sidebar
4. Click delete button (trash icon)
5. Confirm deletion

**Expected:**
- ✅ Session removed from list
- ✅ Chat area shows "Start a conversation"
- ✅ Toast: "Conversation deleted"

**Failure modes:**
- ❌ Delete button doesn't appear on hover
- ❌ Session still appears after deletion
- ❌ Error message instead of deletion

---

## API Call Tracing

### Monitor Network Requests
**Browser DevTools → Network tab:**

**Signup Flow:**
```
POST /auth/signup
{
  "name": "John Doe",
  "email": "john@test.com",
  "password": "SecurePass123!"
}

Response:
{
  "success": true,
  "data": {
    "user": { "user_id": "...", "name": "John Doe", "email": "john@test.com" },
    "access_token": "eyJ...",
    "refresh_token": "eyJ..."
  }
}
```

**Create Session Flow:**
```
POST /sessions
Headers: Authorization: Bearer <access_token>
{
  "title": "Conversation 2024-01-15 14:30",
  "lang": "en"
}

Response:
{
  "success": true,
  "data": {
    "session_id": "abc123...",
    "title": "...",
    "lang": "en",
    "created_at": "2024-01-15T14:30:00Z",
    "user_id": "user_abc..."
  }
}
```

**Send Message Flow:**
```
POST /sessions/abc123/chat/text
Headers: Authorization: Bearer <access_token>
Body: FormData { text: "Hello" }

Response:
{
  "success": true,
  "data": {
    "message_id": "msg123...",
    "response_text": "Hi there!",
    "detected_langs": ["en"],
    "dominant_lang": "en",
    "audio_base64": "..."
  }
}
```

---

## Debugging Tips

### Check localStorage
```javascript
// In browser console:
console.log({
  access_token: localStorage.getItem('access_token'),
  refresh_token: localStorage.getItem('refresh_token'),
  token_exp: JSON.parse(atob(localStorage.getItem('access_token')?.split('.')[1] || '{}'))}
)
```

### Monitor WebSocket
```javascript
// Override ws onmessage to log all messages
const originalOnMessage = ws.onmessage;
ws.onmessage = (evt) => {
  console.log('[WS]', JSON.parse(evt.data));
  originalOnMessage.call(ws, evt);
};
```

### Check Current User
```javascript
// In browser console:
console.log('Current User:', currentUser);
console.log('Access Token Valid:', !!accessToken);
console.log('Active Session:', activeSessionId);
```

### Force Test Mode
```javascript
// Simulate 401 error:
refreshAccessToken(); // Will fail and show logout

// Clear auth:
logout(); // Manual logout

// Restore auth:
localStorage.setItem('access_token', '<token>');
localStorage.setItem('refresh_token', '<token>');
location.reload();
```

---

## Common Issues & Solutions

| Issue | Cause | Fix |
|-------|-------|-----|
| "Not authenticated" on send | No access_token | Check localStorage, login again |
| CORS error | Backend CORS not configured | Add `CORS_ORIGINS=*` or specific domain |
| Auth modal keeps showing | Token refresh failing | Check refresh_token expiry |
| Messages disappear on refresh | Session not user-scoped | Backend not filtering by user_id |
| WebSocket won't connect | Token param missing | Check `wsConnect()` URL format |
| Password validation error | New password doesn't meet policy | Check 8+ chars, upper, lower, digit, special |

---

## Success Criteria

✅ All tests pass if:
- [ ] Users can signup with valid credentials
- [ ] Users can login with correct email/password
- [ ] Users cannot login with wrong password
- [ ] User A's sessions don't appear for User B
- [ ] Messages send successfully with auth header
- [ ] WebSocket connects with token parameter
- [ ] Token auto-refreshes on 401
- [ ] Logout clears tokens and shows auth modal
- [ ] Password change logs out other sessions
- [ ] Conversations can be created and deleted
- [ ] Language detection works
- [ ] Audio playback works
- [ ] Voice recording works

---

**Ready to test! 🚀**

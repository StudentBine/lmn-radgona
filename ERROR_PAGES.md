# Error Pages - Dokumentacija

## 📋 Pregled

Aplikacija uporablja **custom error strani** za boljšo uporabniško izkušnjo. Namesto grdih privzetih Flask error strani, uporabniki vidijo lepe, prijazne error strani.

## ✅ Podprte Error Kode

### 404 - Stran ni bila najdena
- **Kdaj:** Ko uporabnik obišče URL, ki ne obstaja
- **Ikona:** 🔍
- **Akcije:** 
  - Domača stran
  - Nazaj (history back)

### 403 - Dostop zavrnjen
- **Kdaj:** Ko uporabnik nima dovoljenja (npr. admin stran brez prijave)
- **Ikona:** 🚫
- **Akcije:** 
  - Domača stran

### 500 - Napaka strežnika
- **Kdaj:** Ko pride do nepričakovane napake v aplikaciji
- **Ikona:** ⚠️
- **Akcije:** 
  - Domača stran
  - Osveži stran

### 503 - Storitev ni na voljo
- **Kdaj:** Ko je storitev začasno nedosegljiva (npr. maintenance)
- **Ikona:** 🔧
- **Akcije:** 
  - Domača stran
  - Osveži stran

### 400 - Napačen zahtevek
- **Kdaj:** Ko je zahtevek nepravilen ali ga ni mogoče obdelati
- **Ikona:** ❌
- **Akcije:** 
  - Domača stran

## 🎨 Vizualne Značilnosti

### Animacije
- **Slide-in** animacija ob nalaganju strani
- **Bounce** animacija za ikono
- **Hover** efekti za gumbe

### Barve
- **Gradient background:** Vijolično-modra (#667eea → #764ba2)
- **Gumbi:** Gradient z shadow efekti
- **Error koda:** Gradient text s transparentnostjo

### Responsive Design
- Deluje na vseh napravah (desktop, tablet, mobile)
- Na mobilnih napravah so gumbi v navpični postavitvi

## 🔧 Testiranje Error Strani

### V Development Mode
Obiščite test endpoint:

```
http://localhost:5000/test-error/404  # Test 404 page
http://localhost:5000/test-error/403  # Test 403 page
http://localhost:5000/test-error/500  # Test 500 page
http://localhost:5000/test-error/503  # Test 503 page
http://localhost:5000/test-error/400  # Test 400 page
```

**Opomba:** Test endpoint je onemogočen v production mode!

### V Production Mode
Test endpoint ne deluje - morate sprožiti pravo napako:

```
# 404 test
http://your-domain.com/ne-obstaja

# 403 test
http://your-domain.com/admin  # Brez prijave

# 500 test
Lahko sprožite napako v kodi (ne priporočeno)
```

## 💻 API Responses

Če je zahtevek API zahtevek (path začne z `/api/` ali `Accept: application/json`), se vrne JSON:

```json
{
  "error": "Not Found",
  "message": "The requested resource was not found",
  "code": 404
}
```

## 🛠️ Implementacija

### Error Handler v app_radgona.py

```python
@app.errorhandler(404)
def page_not_found(e):
    """Handle 404 - Page Not Found errors"""
    logger.warning(f"404 error: {request.url}")
    
    # API request → JSON response
    if request.path.startswith('/api/') or request.accept_mimetypes.accept_json:
        return jsonify({
            'error': 'Not Found',
            'message': 'The requested resource was not found',
            'code': 404
        }), 404
    
    # Browser request → HTML template
    return render_template('error.html', 
                         error_code=404,
                         error_message=None), 404
```

### Error Template (error.html)

Template uporablja:
- `error_code` - številka napake (404, 500, itd.)
- `error_message` - custom sporočilo (opcijsko)

```html
<!-- Če error_message ni podano, se uporabi privzeto sporočilo glede na kodo -->
<p class="error-message">
    {% if error_message %}
        {{ error_message }}
    {% elif error_code == 404 %}
        Iskana stran ne obstaja. Morda je bila premaknjena ali izbrisana.
    {% endif %}
</p>
```

## 📝 Dodajanje Nove Error Strani

### 1. Dodaj Error Handler

```python
@app.errorhandler(418)  # I'm a teapot ;)
def im_a_teapot(e):
    """Handle 418 - I'm a teapot"""
    logger.warning(f"418 error: Someone tried to brew coffee")
    
    if request.path.startswith('/api/') or request.accept_mimetypes.accept_json:
        return jsonify({
            'error': "I'm a teapot",
            'message': 'I refuse to brew coffee because I am a teapot',
            'code': 418
        }), 418
    
    return render_template('error.html',
                         error_code=418,
                         error_message='Ne morem skuhati kave, ker sem čajnik! ☕'), 418
```

### 2. Dodaj CSS za Ikono (opcijsko)

V `error.html` template:

```css
.error-418 .error-icon::before {
    content: "☕";
}
```

### 3. Dodaj Custom Besedilo (opcijsko)

V `error.html` template:

```html
{% elif error_code == 418 %}
    Ne morem skuhati kave
```

## 🎯 Best Practices

### ✅ Dobro

```python
# Uporabi error handler
@app.route('/api/data')
def get_data():
    if not data_exists:
        abort(404)  # Sproži 404 error handler
```

### ❌ Slabo

```python
# Ne vrni direktno HTML string
@app.route('/api/data')
def get_data():
    if not data_exists:
        return "<h1>Not Found</h1>", 404  # Grdo!
```

## 🔍 Logging

Vsi errorji se logirajo:

```python
# 404 errors → WARNING level
logger.warning(f"404 error: {request.url}")

# 500 errors → ERROR level with traceback
logger.error(f"500 error: {request.url} - {str(e)}", exc_info=True)
```

Preverjanje logov:

```bash
# Na Render
Dashboard → Service → Logs

# Lokalno
# Logi se prikažejo v terminalu kjer teče Flask app
```

## 🚀 Production Deployment

### Render
Error handlers delujejo avtomatsko. Ni potrebna nobena posebna konfiguracija.

### Environment Variables
```bash
FLASK_ENV=production  # Test endpoint bo onemogočen
```

## 🎨 Prilagajanje Stila

Če želite spremeniti barve/animacije, uredite CSS v `templates/error.html`:

```css
/* Spremeni gradient barve */
.error-container {
    background: linear-gradient(135deg, #FF6B6B 0%, #4ECDC4 100%);
}

/* Spremeni barvo gumbov */
.btn-error {
    background: linear-gradient(135deg, #FF6B6B 0%, #C44569 100%);
}
```

## 📊 Statistika Errorjev

Če želite slediti errorjem, lahko dodate v logger:

```python
@app.errorhandler(404)
def page_not_found(e):
    logger.warning(f"404 error: {request.url} | Referrer: {request.referrer}")
    # ... ostalo
```

## ✅ Checklist

- [x] Error handlerji dodani za: 400, 403, 404, 500, 503
- [x] Custom error.html template z lepim dizajnom
- [x] API requests vračajo JSON
- [x] Browser requests vračajo HTML
- [x] Test endpoint za development
- [x] Logging za vse errorje
- [x] Responsive design
- [x] Animacije in hover efekti
- [x] Kontaktne informacije za pomoč
- [x] Različne akcije za različne error kode

## 🎉 Rezultat

Uporabniki sedaj vidijo **prijazne, profesionalne error strani** namesto grdih privzetih Flask errorjev! 🚀

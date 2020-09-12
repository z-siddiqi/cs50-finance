import os

from cs50 import SQL
from flask import Flask, flash, jsonify, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# configure application
app = Flask(__name__)

# ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

# custom filter
app.jinja_env.filters["usd"] = usd

# configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks."""

    # query database for user's stocks
    rows = db.execute("SELECT * FROM stocks WHERE user_id = :user",
                      user=session["user_id"])

    # query database for user's cash
    cash = db.execute("SELECT cash FROM users WHERE id = :user",
                      user=session["user_id"])[0]['cash']

    # pass a list of dicts to the template page
    total = cash
    stocks = []
    for row in rows:
        stock_info = lookup(row['symbol'])

        info = {
            'symbol': stock_info['symbol'],
            'name': stock_info['name'],
            'shares': row['amount'],
            'price': stock_info['price'],
            'value': round(stock_info['price'] * row['amount'], 2)
        }

        stocks.append(info)
        total += info['value']  # add the shares value

    return render_template("index.html", stocks=stocks, cash=usd(cash), value=usd(total))


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock."""

    # user reached route via POST
    if request.method == "POST":
        req_amount = int(request.form.get("amount"))
        req_symbol = request.form.get("symbol")

        # check if symbol is valid
        if not lookup(req_symbol):
            return apology("stock not found", 403)

        # check user entered a positive integer
        elif int(req_amount) <= 0:
            return apology("number of shares must be a positive integer", 403)

        # query database for user's cash
        cash = db.execute("SELECT cash FROM users WHERE id = :user",
                          user=session["user_id"])[0]['cash']

        # calculate cost of the transaction
        price = lookup(req_symbol)['price']
        cost = price * req_amount

        if cost > cash:
            return apology("insufficient funds", 403)

        # check user's current holdings for any shares of this stock
        stock = db.execute("SELECT amount FROM stocks WHERE user_id = :user AND symbol = :symbol",
                           user=session["user_id"], symbol=req_symbol)

        # add/ update stock from table
        if not stock:
            db.execute("INSERT INTO stocks(user_id, symbol, amount) VALUES (:user, :symbol, :amount)",
                       user=session["user_id"], symbol=req_symbol, amount=req_amount)
        else:
            amount += stock[0]['amount']

            db.execute("UPDATE stocks SET amount = :amount WHERE user_id = :user AND symbol = :symbol",
                       user=session["user_id"], symbol=req_symbol, amount=req_amount)

        # update user's cash
        updated_cash = cash - cost
        db.execute("UPDATE users SET cash = :cash WHERE id = :user",
                   cash=updated_cash, user=session["user_id"])

        # update history table
        db.execute("INSERT INTO transactions(user_id, symbol, amount, value) VALUES (:user, :symbol, :amount, :value)",
                   user=session["user_id"], symbol=req_symbol, amount=req_amount, value=usd(cost))

        # redirect user
        flash("Bought!")
        return redirect("/")

    # user reached route via GET
    else:
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    """Show history of transactions."""

    # query database for user's transactions
    rows = db.execute("SELECT * FROM transactions WHERE user_id = :user",
                      user=session["user_id"])

    # pass a list of dicts to the template page
    transactions = []
    for row in rows:
        stock_info = lookup(row['symbol'])

        info = {
            'symbol': stock_info['symbol'],
            'name': stock_info['name'],
            'shares': row['amount'],
            'value': row['value'],
            'date': row['date']
        }

        transactions.append(info)

    return render_template("history.html", transactions=transactions)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in."""

    # forget any user_id
    session.clear()

    # user reached route via POST
    if request.method == "POST":
        req_username = request.form.get("username")
        req_password = request.form.get("password")

        # check username was submitted
        if not req_username:
            return apology("must provide username", 403)

        # check password was submitted
        elif not req_password:
            return apology("must provide password", 403)

        # query database for username
        rows = db.execute(
            "SELECT * FROM users WHERE username = :username",
            username=req_username
        )

        # ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], req_password):
            return apology("invalid username and/or password", 403)

        # remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # redirect user
        flash(f"Logged in as {req_username}.")
        return redirect("/")

    # user reached route via GET
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out."""

    # forget any user_id
    session.clear()

    # redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""

    # user reached route via POST
    if request.method == "POST":

        # look up stock info
        stock = lookup(request.form.get("symbol"))

        if not stock:
            return apology("stock not found", 403)

        return render_template("quote.html", stock=stock)

    # user reached route via GET
    else:
        return render_template("quote.html", stock="")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user."""

    # forget any user_id
    session.clear()

    # user reached route via POST
    if request.method == "POST":
        req_username = request.form.get("username")
        req_password = request.form.get("password")
        req_confirmation = request.form.get("confirm-password")

        # check username was submitted
        if not req_username:
            return apology("must provide username", 403)

        # check password was submitted
        elif not req_password:
            return apology("must provide password", 403)

        # check passwords match
        elif req_password != req_confirmation:
            return apology("the passwords don't match", 403)

        # check username doesn't already exist
        elif db.execute("SELECT * FROM users WHERE username = :username",
                        username=req_username):
            return apology("username already taken", 403)

        # insert user details into the table
        db.execute("INSERT INTO users(username, hash) VALUES (:username, :hash)",
                   username=req_username,hash=generate_password_hash(req_password))

        # query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=req_username)

        # remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # redirect user
        return redirect("/")

    # user reached route via POST
    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock."""

    # user reached route via POST
    if request.method == "POST":
        req_amount = int(request.form.get("amount"))
        req_symbol = request.form.get("symbol")

        # check if symbol is valid
        if not lookup(req_symbol):
            return apology("stock not found", 403)

        # check user entered a positive integer
        elif req_amount <= 0:
            return apology("number of shares must be a positive integer", 403)

        # query database for user's initial amount of stock
        initial_amount = db.execute("SELECT amount FROM stocks WHERE user_id = :user AND symbol = :symbol",
                                    symbol=req_symbol, user=session["user_id"])[0]['amount']

        # check user has enough shares to sell
        if initial_amount < req_amount:
            return apology("not enough shares", 403)

        # calculate cost of the transaction
        price = lookup(req_symbol)['price']
        cost = price * req_amount

        # calculate new amount of shares
        updated_amount = initial_amount - req_amount

        # delete/ update stock from table
        if updated_amount == 0:
            db.execute("DELETE FROM stocks WHERE user_id = :user AND symbol = :symbol",
                       symbol=req_symbol, user=session["user_id"])
        else:
            db.execute("UPDATE stocks SET amount = :amount WHERE user_id = :user AND symbol = :symbol",
                       symbol=req_symbol, user=session["user_id"], amount=updated_amount)

        # calculate and update user's cash
        initial_cash = db.execute("SELECT cash FROM users WHERE id = :user",
                                  user=session["user_id"])[0]['cash']

        updated_cash = initial_cash + round(cost, 2)

        db.execute("UPDATE users SET cash = :cash WHERE id = :user",
                   cash=updated_cash, user=session["user_id"])

        # update history table
        db.execute("INSERT INTO transactions(user_id, symbol, amount, value) VALUES (:user, :symbol, :amount, :value)",
                   user=session["user_id"], symbol=req_symbol, amount=-req_amount, value=usd(cost))

        # redirect user
        flash("Sold!")
        return redirect("/")

    # user reached route via GET
    else:

        # query database for user's stocks
        rows = db.execute("SELECT symbol, amount FROM stocks WHERE user_id = :user",
                          user=session["user_id"])

        # create a dictionary of the stocks and their amounts
        stocks = {}
        for row in rows:
            stocks[row['symbol']] = row['amount']

        return render_template("sell.html", stocks=stocks)


@app.route("/addcash", methods=["GET", "POST"])
@login_required
def add_cash():
    """Add cash to balance."""

    # user reached route via POST
    if request.method == "POST":
        req_amount = int(request.form.get("amount"))

        # check user entered a positive integer
        if req_amount <= 0:
            return apology("amount of cash must be a positive integer", 403)

        # calculate and update user's cash
        initial_cash = db.execute("SELECT cash FROM users WHERE id = :user",
                                  user=session["user_id"])[0]['cash']

        updated_cash = initial_cash + req_amount

        db.execute("UPDATE users SET cash = :cash WHERE id = :user",
                   cash=updated_cash, user=session["user_id"])

        # redirect user
        flash("Cash added!")
        return redirect("/")

    # user reached route via GET
    else:
        return render_template("addcash.html")


def errorhandler(e):
    """Handle error."""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)

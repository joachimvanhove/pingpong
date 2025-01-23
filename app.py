import eventlet
eventlet.monkey_patch()  # Dit moet de eerste regel zijn

from flask import Flask, render_template, request, redirect
from flask_socketio import SocketIO
import sqlite3

# De rest van je app-logica
app = Flask(__name__)
socketio = SocketIO(app)

# Database connectie
def get_db_connection():
    conn = sqlite3.connect('pingpong.db')  # Verwijst naar het bestand in de huidige map
    conn.row_factory = sqlite3.Row
    return conn

# Dashboard
@app.route("/")
def index():
    return render_template("dashboard.html")

# Leaderboard
@app.route("/leaderboard")
def leaderboard():
    conn = get_db_connection()
    players = conn.execute("""
        SELECT p.name AS player_name,
               COUNT(g.id) AS games_played,
               SUM(CASE WHEN g.player1 = p.name AND g.score1 > g.score2 THEN 1
                        WHEN g.player2 = p.name AND g.score2 > g.score1 THEN 1 ELSE 0 END) AS wins,
               1000 + (SUM(CASE WHEN g.player1 = p.name AND g.score1 > g.score2 THEN 1
                                WHEN g.player2 = p.name AND g.score2 > g.score1 THEN 1 ELSE 0 END) * 10) AS elo
        FROM players p
        LEFT JOIN games g ON g.player1 = p.name OR g.player2 = p.name
        GROUP BY p.name
    """).fetchall()
    conn.close()
    return render_template("leaderboard.html", players=players)

# Spelerbeheer
@app.route("/players", methods=["GET", "POST"])
def players():
    conn = get_db_connection()
    if request.method == "POST":
        name = request.form["name"]
        conn.execute("INSERT INTO players (name) VALUES (?)", (name,))
        conn.commit()
        return redirect("/players")
    players = conn.execute("SELECT * FROM players").fetchall()
    conn.close()
    return render_template("players.html", players=players)

# Spelerselectie
@app.route("/player1", methods=["GET", "POST"])
@app.route("/player2", methods=["GET", "POST"])
def player_select():
    player = "Player 1" if request.path == "/player1" else "Player 2"
    conn = get_db_connection()
    if request.method == "POST":
        name = request.form["player_name"]
        if player == "Player 1":
            conn.execute("UPDATE current_game SET player1=? WHERE id=1", (name,))
            conn.commit()
            conn.close()
            return redirect("/player1_score")  # Correcte redirect naar player1_score
        else:
            conn.execute("UPDATE current_game SET player2=? WHERE id=1", (name,))
            conn.commit()
            conn.close()
            return redirect("/player2_score")  # Correcte redirect naar player2_score

    players = conn.execute("SELECT * FROM players").fetchall()
    conn.close()
    return render_template("player_select.html", player=player, players=players)

# Live score
@app.route("/live_score")
def live_score():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT player1, player2, score1, score2 FROM current_game WHERE id = 1")
    game = cursor.fetchone()
    conn.close()

    if game:
        player1, player2, score1, score2 = game
        total_points = score1 + score2

        # Server-logica
        if total_points >= 20 and score1 == score2:  # Bij deuce
            server = "player1" if total_points % 2 == 0 else "player2"
        else:  # Normale situatie
            server = "player1" if (total_points // 2) % 2 == 0 else "player2"

        return render_template(
            "live_score.html",
            player1=player1,
            player2=player2,
            score1=score1,
            score2=score2,
            server=server
        )
    else:
        # Geen actieve game
        return "No active game. Please start a new game.", 404

# Score verhogen
@app.route("/player1_score", methods=["GET", "POST"])
def player1_score():
    conn = get_db_connection()
    if request.method == "POST":
        # Verhoog de score van Player 1
        conn.execute("UPDATE current_game SET score1 = score1 + 1 WHERE id = 1")
        conn.commit()

        # Haal de bijgewerkte scores op
        cursor = conn.cursor()
        cursor.execute("SELECT player1, player2, score1, score2 FROM current_game WHERE id = 1")
        game = cursor.fetchone()
        if game:
            score1, score2 = game[2], game[3]
            # Controleer of Player 1 heeft gewonnen
            if score1 >= 11 and score1 >= score2 + 2:
                # Stuur WebSocket-update voor einde game
                socketio.emit('end_game', {
                    'winner': game[0],
                    'loser': game[1],
                    'winner_score': score1,
                    'loser_score': score2
                })
                conn.close()
                return redirect("/end_game")

            # WebSocket-update voor score
            total_points = score1 + score2
            server = (
                "player1" if total_points >= 20 and score1 == score2 else
                "player1" if (total_points // 2) % 2 == 0 else "player2"
            )
            socketio.emit('update_score', {
                'player1': game[0],
                'score1': score1,
                'player2': game[1],
                'score2': score2,
                'server': server
            })
        conn.close()
        return redirect("/player1_score")

    # Haal gegevens op
    cursor = conn.cursor()
    cursor.execute("SELECT player1, player2, score1, score2 FROM current_game WHERE id = 1")
    game = cursor.fetchone()
    conn.close()

    if game:
        total_points = game[2] + game[3]
        server = (
            "player1" if total_points >= 20 and game[2] == game[3] else
            "player1" if (total_points // 2) % 2 == 0 else "player2"
        )
        return render_template(
            "player_score.html",
            player=game[0],
            player_score=game[2],
            opponent=game[1],
            opponent_score=game[3],
            server=server == "player1"
        )
    else:
        return "No active game. Please start a new game.", 404

@app.route("/player2_score", methods=["GET", "POST"])
def player2_score():
    conn = get_db_connection()
    if request.method == "POST":
        # Verhoog de score van Player 2
        conn.execute("UPDATE current_game SET score2 = score2 + 1 WHERE id = 1")
        conn.commit()

        # Haal de bijgewerkte scores op
        cursor = conn.cursor()
        cursor.execute("SELECT player1, player2, score1, score2 FROM current_game WHERE id = 1")
        game = cursor.fetchone()
        if game:
            score1, score2 = game[2], game[3]
            # Controleer of Player 2 heeft gewonnen
            if score2 >= 11 and score2 >= score1 + 2:
                # Stuur WebSocket-update voor einde game
                socketio.emit('end_game', {
                    'winner': game[1],
                    'loser': game[0],
                    'winner_score': score2,
                    'loser_score': score1
                })
                conn.close()
                return redirect("/end_game")

            # WebSocket-update voor score
            total_points = score1 + score2
            server = (
                "player1" if total_points >= 20 and score1 == score2 else
                "player1" if (total_points // 2) % 2 == 0 else "player2"
            )
            socketio.emit('update_score', {
                'player1': game[0],
                'score1': score1,
                'player2': game[1],
                'score2': score2,
                'server': server
            })
        conn.close()
        return redirect("/player2_score")

    # Haal gegevens op
    cursor = conn.cursor()
    cursor.execute("SELECT player1, player2, score1, score2 FROM current_game WHERE id = 1")
    game = cursor.fetchone()
    conn.close()

    if game:
        total_points = game[2] + game[3]
        server = (
            "player1" if total_points >= 20 and game[2] == game[3] else
            "player1" if (total_points // 2) % 2 == 0 else "player2"
        )
        return render_template(
            "player_score.html",
            player=game[1],
            player_score=game[3],
            opponent=game[0],
            opponent_score=game[2],
            server=server == "player2"
        )
    else:
        return "No active game. Please start a new game.", 404

# Reset game
@app.route("/reset_game", methods=["POST"])
def reset_game():
    conn = get_db_connection()
    conn.execute("UPDATE current_game SET player1=NULL, player2=NULL, score1=0, score2=0 WHERE id=1")
    conn.commit()
    conn.close()
    return redirect("/")

# Gamegeschiedenis
@app.route("/games")
def games():
    conn = get_db_connection()
    games = conn.execute("SELECT * FROM games").fetchall()
    conn.close()
    return render_template("games.html", games=games)

# End game
@app.route("/end_game")
def end_game():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT player1, player2, score1, score2 FROM current_game WHERE id = 1")
    game = cursor.fetchone()
    conn.close()

    if game:
        # Identificeer de winnaar
        if game[2] > game[3]:
            winner = game[0]
            loser = game[1]
            winner_score = game[2]
            loser_score = game[3]
        else:
            winner = game[1]
            loser = game[0]
            winner_score = game[3]
            loser_score = game[2]

        return render_template(
            "end_game.html",
            winner=winner,
            loser=loser,
            winner_score=winner_score,
            loser_score=loser_score
        )
    else:
        return "No active game to end.", 404

import eventlet
eventlet.monkey_patch()

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5555, debug=True)

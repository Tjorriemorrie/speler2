GENRE_CHRISTIAN = 'christian'
GENRE_POP_DANCE = 'pop and dance'
GENRE_SOFT_ROCK = 'soft rock'
GENRE_HARD_ROCK = 'hard rock'
GENRE_METAL = 'metal'

LIST_GENRES = [
    GENRE_CHRISTIAN,
    GENRE_POP_DANCE,
    GENRE_SOFT_ROCK,
    GENRE_HARD_ROCK,
    GENRE_METAL,
]

GENRE_CHOICES = [
    [GENRE_CHRISTIAN, GENRE_CHRISTIAN],
    [GENRE_POP_DANCE, GENRE_POP_DANCE],
    [GENRE_SOFT_ROCK, GENRE_SOFT_ROCK],
    [GENRE_HARD_ROCK, GENRE_HARD_ROCK],
    [GENRE_METAL, GENRE_METAL],
]

BILLBOARD_CHART_ROCK = 'rock'
BILLBOARD_CHART_ALTERNATIVE = 'alternative'
BILLBOARD_CHART_HARD_ROCK = 'hard rock'
BILLBOARD_CHART_CHRISTIAN = 'christian'

BILLBOARD_CHOICES = [
    [BILLBOARD_CHART_ROCK, BILLBOARD_CHART_ROCK],
    [BILLBOARD_CHART_ALTERNATIVE, BILLBOARD_CHART_ALTERNATIVE],
    [BILLBOARD_CHART_HARD_ROCK, BILLBOARD_CHART_HARD_ROCK],
    [BILLBOARD_CHART_CHRISTIAN, BILLBOARD_CHART_CHRISTIAN],
]

BILLBOARD_CHART_URLS = {
    BILLBOARD_CHART_ROCK: 'https://www.billboard.com/charts/rock-albums/',
    BILLBOARD_CHART_ALTERNATIVE: 'https://www.billboard.com/charts/alternative-albums/',
    BILLBOARD_CHART_HARD_ROCK: 'https://www.billboard.com/charts/hard-rock-albums/',
    BILLBOARD_CHART_CHRISTIAN: 'https://www.billboard.com/charts/christian-albums/',
}

AZLYRICS_ARTISTS = {
    'aperfectcircle': 'perfectcircle',
    'u2': 'u2band',
}

AZLYRICS_SONGS = {
    'bettermanthecage': 'betterman',  # oasis
    'burningthemaps': 'burningthemap',  # better than ezra
    'gimmestitches': 'gimmiestitches',  # foo fighters
    'pinata': 'piata',  # chevelle
    'tumbleandfall': 'tumblefall',  # feeder
}

-- Schema and reporting queries for a small online bookshop.

CREATE TABLE author (
    author_id   integer PRIMARY KEY,
    full_name   varchar(120) NOT NULL,
    country     char(2)
);

CREATE TABLE book (
    book_id     integer PRIMARY KEY,
    author_id   integer NOT NULL REFERENCES author (author_id),
    title       varchar(200) NOT NULL,
    genre       varchar(40) NOT NULL,
    price       numeric(8, 2) NOT NULL CHECK (price > 0),
    published   date,
    stock       integer NOT NULL DEFAULT 0 CHECK (stock >= 0)
);

CREATE TABLE customer_order (
    order_id    integer PRIMARY KEY,
    placed_at   timestamp NOT NULL DEFAULT current_timestamp,
    status      varchar(12) NOT NULL DEFAULT 'new'
                CHECK (status IN ('new', 'paid', 'shipped', 'cancelled')),
    country     char(2) NOT NULL
);

CREATE TABLE order_line (
    order_id    integer NOT NULL REFERENCES customer_order (order_id) ON DELETE CASCADE,
    book_id     integer NOT NULL REFERENCES book (book_id),
    quantity    integer NOT NULL CHECK (quantity > 0),
    unit_price  numeric(8, 2) NOT NULL,
    PRIMARY KEY (order_id, book_id)
);

CREATE INDEX book_genre_idx ON book (genre);
CREATE INDEX order_placed_idx ON customer_order (placed_at);

-- Monthly revenue from orders that were paid or shipped.
SELECT date_trunc('month', o.placed_at) AS month,
       count(DISTINCT o.order_id)        AS orders,
       sum(l.quantity * l.unit_price)    AS revenue
FROM customer_order o
JOIN order_line l ON l.order_id = o.order_id
WHERE o.status IN ('paid', 'shipped')
GROUP BY date_trunc('month', o.placed_at)
ORDER BY month;

-- The five best-selling books in each genre.
WITH sales AS (
    SELECT b.genre, b.title, sum(l.quantity) AS copies
    FROM order_line l
    JOIN book b ON b.book_id = l.book_id
    GROUP BY b.genre, b.title
), ranked AS (
    SELECT genre, title, copies,
           row_number() OVER (PARTITION BY genre ORDER BY copies DESC, title) AS position
    FROM sales
)
SELECT genre, position, title, copies
FROM ranked
WHERE position <= 5
ORDER BY genre, position;

-- Authors whose books have never been ordered.
SELECT a.full_name
FROM author a
WHERE NOT EXISTS (
    SELECT 1
    FROM book b
    JOIN order_line l ON l.book_id = b.book_id
    WHERE b.author_id = a.author_id
)
ORDER BY a.full_name;

-- Books that are running low, with the number sold in the last thirty days.
SELECT b.title,
       b.stock,
       coalesce(sum(l.quantity) FILTER (
           WHERE o.placed_at >= current_date - interval '30 days'), 0) AS sold_recently
FROM book b
LEFT JOIN order_line l ON l.book_id = b.book_id
LEFT JOIN customer_order o ON o.order_id = l.order_id AND o.status <> 'cancelled'
GROUP BY b.book_id, b.title, b.stock
HAVING b.stock < 10
ORDER BY sold_recently DESC, b.stock;

-- Raise the price of every book in one genre by five per cent, rounded to the cent.
UPDATE book
SET price = round(price * 1.05, 2)
WHERE genre = 'travel';

-- Cancel new orders that have not been paid within a week.
UPDATE customer_order
SET status = 'cancelled'
WHERE status = 'new'
  AND placed_at < current_timestamp - interval '7 days';

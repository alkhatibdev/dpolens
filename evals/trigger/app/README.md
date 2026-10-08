# Larder

The backend for Larder, an online grocery shop that delivers from local shops on the same day:
customer accounts, the product catalogue and orders, plus the shop's front page.

## Running it

```bash
npm install
cp .env.example .env
npx prisma migrate dev
npm run dev
```

The API listens on port 3000 and serves the front page from `public/`.

## Layout

| Path | What it holds |
| --- | --- |
| `src/routes` | The HTTP routes: sign up and log in, products, orders, the customer's account |
| `src/services` | Accounts and orders |
| `src/lib` | Logging, analytics through Segment, email through Postmark, money helpers |
| `src/middleware` | Request logging, the session check, error responses |
| `prisma/schema.prisma` | The database schema |
| `public` | The front page |

## Checks

```bash
npm run typecheck
npm test
```

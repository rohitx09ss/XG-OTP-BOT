import { countries } from "./_data.js";
import { generateNational } from "./_format.js";

// GET /api/number?country=IN            -> 1 number
// GET /api/number?country=IN&count=10   -> 10 alag-alag numbers
export default function handler(req, res) {
  const c = countries.find(
    (x) => x.code === (req.query.country || "").toUpperCase()
  );
  if (!c) return res.status(400).json({ error: "Invalid country" });

  const count = Math.min(Math.max(parseInt(req.query.count) || 1, 1), 20);
  const set = new Set();
  let tries = 0;
  while (set.size < count && tries++ < count * 50) {
    set.add(c.dial + generateNational(c.code));
  }
  const numbers = [...set];

  res.json({
    country: c.code,
    name: c.name,
    price: c.price,
    dial: c.dial,
    number: numbers[0],
    numbers,
  });
}

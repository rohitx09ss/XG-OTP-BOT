import { countries } from "./_data.js";

export default function handler(req, res) {
  res.json(countries);
}

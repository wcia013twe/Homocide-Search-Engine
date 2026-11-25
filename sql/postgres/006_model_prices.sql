CREATE TABLE IF NOT EXISTS research_model_prices (
 actor TEXT NOT NULL, endpoint TEXT NOT NULL,
 input_price NUMERIC NOT NULL CHECK (input_price >= 0),
 output_price NUMERIC NOT NULL CHECK (output_price >= 0),
 PRIMARY KEY (actor, endpoint)
);

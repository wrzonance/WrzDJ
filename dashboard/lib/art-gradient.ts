const ART_GRADIENTS = [
  'linear-gradient(135deg, #ff006e, #8338ec, #3a86ff)',
  'linear-gradient(135deg, #ffbe0b, #fb5607)',
  'linear-gradient(135deg, #06ffa5, #0077b6)',
  'linear-gradient(135deg, #ff6b9d, #c44569)',
  'linear-gradient(135deg, #f72585, #7209b7)',
  'linear-gradient(135deg, #4cc9f0, #4361ee)',
  'linear-gradient(135deg, #f15bb5, #fee440)',
  'linear-gradient(135deg, #2dc653, #25a244)',
  'linear-gradient(135deg, #ef476f, #ffd166)',
];

export function artGradient(seed: string): string {
  const code = (seed.charCodeAt(0) || 0) + (seed.charCodeAt(1) || 0);
  return ART_GRADIENTS[code % ART_GRADIENTS.length];
}

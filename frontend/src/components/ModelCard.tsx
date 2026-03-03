interface ModelCardProps {
  slug: string;
  displayName: string;
  paramsB: number;
  quantization: string;
  gpuType: string;
  status: string;
  costInput: number;
  costOutput: number;
  description: string | null;
}

const statusColors: Record<string, string> = {
  active: "bg-green-500/20 text-green-400",
  pending: "bg-yellow-500/20 text-yellow-400",
  deploying: "bg-blue-500/20 text-blue-400",
  inactive: "bg-gray-500/20 text-gray-400",
};

export default function ModelCard({
  slug,
  displayName,
  paramsB,
  quantization,
  gpuType,
  status,
  costInput,
  costOutput,
  description,
}: ModelCardProps) {
  return (
    <div className="glass-card glow-border p-6">
      <div className="flex items-start justify-between mb-3">
        <h3 className="text-lg font-semibold text-white">{displayName}</h3>
        <span className={`px-2 py-1 rounded-full text-xs font-medium ${statusColors[status] || statusColors.inactive}`}>
          {status}
        </span>
      </div>

      <p className="text-gray-400 text-sm mb-4 line-clamp-2">
        {description || `${paramsB}B parameter model`}
      </p>

      <div className="flex flex-wrap gap-2 mb-4">
        <span className="bg-gray-700 text-gray-300 px-2 py-1 rounded text-xs">
          {paramsB}B
        </span>
        <span className="bg-gray-700 text-gray-300 px-2 py-1 rounded text-xs">
          {quantization}
        </span>
        <span className="bg-gray-700 text-gray-300 px-2 py-1 rounded text-xs">
          {gpuType}
        </span>
      </div>

      <div className="border-t border-gray-700 pt-3">
        <div className="flex justify-between text-sm">
          <span className="text-gray-400">Input</span>
          <span className="text-white">${costInput.toFixed(2)} / 1M tokens</span>
        </div>
        <div className="flex justify-between text-sm mt-1">
          <span className="text-gray-400">Output</span>
          <span className="text-white">${costOutput.toFixed(2)} / 1M tokens</span>
        </div>
      </div>

      <div className="mt-3 pt-3 border-t border-gray-700">
        <code className="text-xs text-gray-500 break-all">{slug}</code>
      </div>
    </div>
  );
}

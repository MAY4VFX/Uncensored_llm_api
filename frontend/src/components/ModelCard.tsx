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

const statusConfig: Record<string, { color: string; dot: string }> = {
  active: { color: "text-terminal-400", dot: "bg-terminal-400" },
  pending: { color: "text-yellow-500", dot: "bg-yellow-500" },
  deploying: { color: "text-blue-400", dot: "bg-blue-400" },
  inactive: { color: "text-surface-700", dot: "bg-surface-700" },
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
  const st = statusConfig[status] || statusConfig.inactive;

  return (
    <div className="ind-card group">
      <div className="flex items-start justify-between mb-4">
        <h3 className="text-sm font-mono font-semibold text-neutral-100 group-hover:text-terminal-400 transition-colors">
          {displayName}
        </h3>
        <span className={`flex items-center text-[10px] font-mono uppercase tracking-widest ${st.color}`}>
          <span className={`status-dot ${st.dot}`} />
          {status}
        </span>
      </div>

      <p className="text-surface-800 text-xs mb-4 line-clamp-2 leading-relaxed">
        {description || `${paramsB}B parameter uncensored model`}
      </p>

      <div className="flex flex-wrap gap-2 mb-4">
        {[`${paramsB}B`, quantization, gpuType].map((tag) => (
          <span key={tag} className="text-[10px] font-mono text-surface-800 border border-surface-400 px-2 py-0.5 uppercase">
            {tag}
          </span>
        ))}
      </div>

      <div className="border-t border-surface-300 pt-3 space-y-1">
        <div className="flex justify-between text-xs font-mono">
          <span className="text-surface-800">input</span>
          <span className="text-neutral-300">${costInput.toFixed(2)}/1M</span>
        </div>
        <div className="flex justify-between text-xs font-mono">
          <span className="text-surface-800">output</span>
          <span className="text-neutral-300">${costOutput.toFixed(2)}/1M</span>
        </div>
      </div>

      <div className="mt-3 pt-3 border-t border-surface-300">
        <code className="text-[10px] font-mono text-surface-700 break-all">{slug}</code>
      </div>
    </div>
  );
}

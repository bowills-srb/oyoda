import * as React from "react";

import { cn } from "../../lib/utils";

export interface SliderProps extends React.InputHTMLAttributes<HTMLInputElement> {}

const Slider = React.forwardRef<HTMLInputElement, SliderProps>(({ className, type, ...props }, ref) => {
  return (
    <input
      type="range"
      className={cn(
        "w-full accent-accent transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      ref={ref}
      {...props}
    />
  );
});
Slider.displayName = "Slider";

export { Slider };

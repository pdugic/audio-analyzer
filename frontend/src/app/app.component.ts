import { Component, OnDestroy, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { BaseChartDirective } from 'ng2-charts';
import { io, Socket } from 'socket.io-client';
import { ChartConfiguration, ChartType } from 'chart.js';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, BaseChartDirective],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css'
})
export class AppComponent implements OnDestroy {
  private socket!: Socket;

  public amplitudeData: ChartConfiguration['data'] ={
        labels: Array.from({ length: 512*50 }, (_, i) => i),
          datasets: [
            {
              data: Array(512*50).fill(0),
              fill: false,
              tension: 0.0
            }
          ]
        };

  public amplitudeOptions: ChartConfiguration['options'] = {
    responsive: true,
    animation: false,
    elements: {point: { radius: 0 }, line: { borderWidth: 1 }},
    scales: { x: { display: false }, y: { min: -1, max: 1 } },
    plugins: {
      decimation: {algorithm: 'lttb', enabled:true, samples: 512},
    },
  };

  public spectrumData: BaseChartDirective['data'] = {
    labels: [],
    datasets: [
      {
        label: 'Spectrum',
        data: []
      }
    ]
  };

  public spectrumOptions: BaseChartDirective['options'] = {
    responsive: true,
    animation: false
  };

  public lineChartType: ChartType = 'line';
  public barChartType: ChartType = 'bar';

  @ViewChild('lineChart') lineChart?: BaseChartDirective;
  @ViewChild('barChart') barChart?: BaseChartDirective;


  constructor() {
    const options = {
      transports: ["websocket"],
      autoConnect: false
    };
    this.socket = io('http://localhost:8000',options);

    this.socket.on('connect', () => {
      console.error('Connected to server');
      this.socket.emit('start_stream', { message:'hello'});
    });

    this.socket.on('audio_frame', (msg: any) => {
      if (msg.amplitude && this.amplitudeData?.datasets?.[0]) {
        this.amplitudeData.datasets[0].data.push(...msg.amplitude);
        if( this.amplitudeData.datasets[0].data.length > 512 * 50) {
          this.amplitudeData.datasets[0].data.splice(0, 512);
        }
      }
      this.lineChart?.update()

      if (msg.spectrum && this.spectrumData?.datasets?.[0]) {
        this.spectrumData.labels = msg.spectrum.freqs.map((x: number) => x.toFixed(0));
        this.spectrumData.datasets[0].data = msg.spectrum.magnitude;
      }
      this.barChart?.update()
    });

    this.socket.on('finished', () => console.log('Audio stream finished.'));

    this.socket.on('disconnect', () => console.error('Disconnected.'));

  }

  ngOnDestroy() {
    this.socket?.disconnect();
  }

  public start(): void {
    this.socket.connect();
  }

  public stop(): void {
    this.socket.disconnect();
  }

}

import { Component, ElementRef, OnDestroy, AfterViewInit, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { BaseChartDirective } from 'ng2-charts';
import { io, Socket } from 'socket.io-client';
import { ChartConfiguration, ChartType } from 'chart.js';
import { Observable, throttleTime, BehaviorSubject } from 'rxjs';
import { HttpClient } from '@angular/common/http';
import { AudioPlayer } from './audio-player';
import { AppConfigService } from './config.service';

const AMPLITUDE_CHUNK_SIZE=100;
const AMPLITUDE_CHUNKS_TO_SHOW=120;
const FILTER_MIN_IN_HZ=20;
const FILTER_MAX_IN_HZ=22000;

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, FormsModule, BaseChartDirective],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css'
})
export class AppComponent implements OnDestroy, AfterViewInit {
  private socket!: Socket;

  public amplitudeData: ChartConfiguration['data'] ={
        labels: Array.from({ length: AMPLITUDE_CHUNK_SIZE*AMPLITUDE_CHUNKS_TO_SHOW }, (_, i) => i),
          datasets: [
            {
              label: 'Amplitude',
              data: Array(AMPLITUDE_CHUNK_SIZE*AMPLITUDE_CHUNKS_TO_SHOW).fill(0),
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
      decimation: {algorithm: 'lttb', enabled:true, samples: 1024},
    },
  };

  public spectrumData: ChartConfiguration['data'] = {
    datasets: [
      {
        label: 'Spectrum',
        data: [],
        yAxisID: 'y',
        xAxisID: 'x'
      }
    ]
  };

  public spectrumOptions: ChartConfiguration['options'] = {
    responsive: true,
    animation: false,
    elements: {
      point: { radius: 0 }, 
      line: { borderWidth: 1, fill: false, tension: 0.5}},
    scales: {
        x: { display: true,
          min: 0,
          max: FILTER_MAX_IN_HZ,
          ticks: { stepSize: 2000 },
          title: {
            text: "Frequency"
          } 
        },
        y: { min: 0, max: 1 } 
    },
  };

  public lineChartType: ChartType = 'line';
  public barChartType: ChartType = 'bar';

  @ViewChild('amplitudeChart') amplitudeChart?: BaseChartDirective;
  @ViewChild('spectrumChart') spectrumChart?: BaseChartDirective;

  public paused = true;
  public low_cut = FILTER_MIN_IN_HZ;
  public high_cut = FILTER_MAX_IN_HZ;

  private receivedSamples = new BehaviorSubject<number>(0);
  public receivedSamplesThrottled$: Observable<number> = this.receivedSamples.pipe(throttleTime(1000));

  private spectrumChartMax = new BehaviorSubject<number>(1);
  public spectrumChartMax$: Observable<number> = this.spectrumChartMax.pipe(throttleTime(500));

  private spectrumMaxLongLast = 0;

  private audioPlayer: AudioPlayer = new AudioPlayer(44100);

  constructor(private http: HttpClient, private appConfig: AppConfigService) {
    const apiUrl = this.appConfig.get<string>('apiUrl', 'http://localhost:8080') as string;
    const url = new URL(apiUrl);

    const protocol = url.protocol; // "http:"
    const host = url.hostname;     // "my_host"
    const port = url.port;         // "port" (as a string)
    const socket_io_path = '/filter/socket.io/';     // "/my_path/path2"

    const options = {
      transports: ["websocket"],
      autoConnect: true,
      path: socket_io_path
    };
    this.socket = io(protocol + '//' + host + ':' + port, options);

    this.socket.on('connect', () => {
      console.log('Connected to server');
      this.socket.emit('start_stream', { message:'hello'});
      this.get_current_filters();
    });

    this.socket.on('audio_frame', (msg: any) => {
      if (msg.amplitude && this.amplitudeData?.datasets?.[0]) {
        if( this.amplitudeData.datasets[0].data.length > AMPLITUDE_CHUNK_SIZE * AMPLITUDE_CHUNKS_TO_SHOW) {
          this.amplitudeData.datasets[0].data.splice(0, AMPLITUDE_CHUNK_SIZE);
        }
        this.amplitudeData.datasets[0].data.push(...msg.amplitude);
      }
      this.amplitudeChart?.update()

      if (msg.spectrum && this.spectrumData?.datasets?.[0]) {
        this.spectrumData.labels = msg.spectrum.freqs;
        this.spectrumData.datasets[0].data = msg.spectrum.magnitude;

        this.spectrumMaxLongLast = Math.max(...msg.spectrum.magnitude);
        this.spectrumChartMax.next(this.spectrumMaxLongLast);
      }
      this.spectrumChart?.update();

      // Play filtered audio (100ms chunks) if present
      if (msg.filtered_raw_data) {
        // enqueue_raw_data could be ArrayBuffer, TypedArray or base64 string depending on server
        try {
          this.audioPlayer.enqueueChunk(msg.filtered_raw_data);
        } catch (e) {
          console.error('Error enqueuing audio chunk', e);
        }
      }

      let buffer = msg.filtered_raw_data;
      let newReceivedSamples = new Int16Array(buffer).length + this.receivedSamples.getValue(); ;
      this.receivedSamples.next(newReceivedSamples);
    });

    this.socket.on('finished', () => console.log('Audio stream finished.'));

    this.socket.on('disconnect', () => console.log('Disconnected.'));

    this.spectrumChartMax$.subscribe(value => this.onSpectrumChartMaxChange(value));
  }

  ngOnDestroy() {
    this.socket?.disconnect();
    this.audioPlayer.close();
  }

  ngAfterViewInit(): void {
    this.pause();
  }
  
  private onSpectrumChartMaxChange(value: number) {
    const currentMax = this.spectrumOptions!.scales!['y']!.max as number;
    if (value > currentMax || 
      value < currentMax * 0.2) {

      const scales = this.spectrumOptions?.scales;
      if (scales?.['y']) {
        scales['y'].max = value * 1.1;
        this.spectrumChart?.render();
      }
    }
  }

  async play(): Promise<void> {
    // resume audio context first (user gesture)
    await this.audioPlayer.play();
    this.paused = false;
  }

  pause(): void {
    this.audioPlayer.pause();
    this.paused = true;
  } 

  private updateFilters() {
    const url = `${this.appConfig.get<string>('apiUrl','http://localhost:8080')}/set-filter`;
    const params = {
      low_cut_in: String(this.low_cut),
      high_cut_in: String(this.high_cut),
    };

    this.http.post(url, null, { params })
      .subscribe({
        next: () => console.log('Filters sent'),
        error: (err) => console.error('Failed to send filters', err)
      });
  }
  
  onLowCutChange(event: Event) {
    const value = (event.target as HTMLInputElement).valueAsNumber;
    if (value >= this.high_cut) {
      this.low_cut = this.high_cut - 1;
    } else if (value < FILTER_MIN_IN_HZ) {
      this.low_cut = FILTER_MIN_IN_HZ;
    } else {
      this.low_cut = value;
    }
    this.updateFilters();
  }

  onHighCutChange(event: Event) {
    const value = (event.target as HTMLInputElement).valueAsNumber;
    if (value <= this.low_cut) {
      this.high_cut = this.low_cut + 1;
    } else if (value > 22000) {
      this.high_cut = 22000;
    } else {
      this.high_cut = value;
    }
    this.updateFilters();
  }

  set_generator(mode: string): void {
    const url = `${this.appConfig.get<string>('apiUrl','http://localhost:8080')}/set-mode`;
    const params = { mode_in: String(mode) };

    this.http.post(url, null, { params })
      .subscribe({
        next: () => console.log('Set mode', mode),
        error: (err) => console.error('Failed to set mode', err)
      });
  }

  get_current_filters(): void {
    this.http.get(`${this.appConfig.get<string>('apiUrl','http://localhost:8080')}/filters`).subscribe({
      next: (f:any) => {
        this.low_cut = f.low_cut;
        this.high_cut = f.high_cut;
       },
      error: (e) => { console.error(e); }
    });
  }

}
